from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config.settings import ALLOW_DEMO_FALLBACK, DATA_MODE_AUTO, DATA_MODE_DEMO, DATA_MODE_LIVE
from domain.recommendations.engine import (
    LongTermRecommendation,
    ShortTermRecommendation,
    build_long_term_recommendation,
    build_short_term_recommendation,
)
from domain.scoring.accounting_quality import (
    AccountingQualityView,
    apply_accounting_overlay,
    build_accounting_quality_view,
)
from domain.scoring.alternative_signals import AlternativeSignalView, build_alternative_signal_view
from domain.scoring.earnings_intelligence import (
    EarningsIntelligenceView,
    build_earnings_intelligence_view,
    build_unavailable_earnings_intelligence_view,
    earnings_intelligence_view_from_dict,
)
from domain.scoring.long_term import LongTermView, build_long_term_view
from domain.scoring.relative_strength import (
    RelativeStrengthView,
    build_relative_strength_view,
    build_unavailable_relative_strength_view,
    relative_strength_view_from_dict,
)
from domain.scoring.short_term import (
    ShortTermView,
    apply_earnings_lockout,
    apply_momentum_context_guard,
    build_short_term_view,
)
from domain.technical.indicators import add_technical_indicators
from providers.events.sec_edgar_client import (
    SecEventBundle,
    build_sec_edgar_client,
    sec_event_bundle_from_dict,
)
from providers.macro.fred_client import (
    FredMacroBundle,
    build_fred_client,
    fred_macro_bundle_from_dict,
)
from providers.market.benchmark_provider import load_relative_strength_benchmarks
from providers.market.market_provider import (
    build_snapshot,
    apply_quote_to_latest_history,
    fetch_earnings_estimate_context,
    fetch_financial_statement_metrics,
    fetch_finnhub_bundle,
    fetch_live_intraday_data,
    load_demo_stock_data,
    load_market_data,
    merge_profile_into_fundamentals,
)
from providers.news.news_provider import (
    apply_long_term_news,
    apply_short_term_news,
    build_news_items,
    score_long_term_news,
    score_short_term_news,
)
from storage.repositories.scan_repository import load_latest_view_scan
from storage.repositories.ticker_repository import load_cached_ticker_data, save_cached_ticker_data


_log = logging.getLogger(__name__)


def _hostile_macro_regime(bundle: FredMacroBundle | None) -> bool:
    if bundle is None or bundle.status not in {"available", "partial"}:
        return False
    financial_conditions = bundle.series.get("financial_conditions")
    high_yield_spread = bundle.series.get("high_yield_spread")
    return bool(
        (financial_conditions and financial_conditions.latest_value >= 0.5)
        or (high_yield_spread and high_yield_spread.latest_value >= 5.5)
    )


@dataclass
class TickerAnalysis:
    ticker: str
    company_name: str
    sector: str
    data_source: str
    intraday_source: str
    status_message: str | None
    intraday_status_message: str | None
    updated_at: str | None
    fundamentals: dict[str, Any]
    statement_metrics: dict[str, Any]
    quote: dict[str, Any]
    profile: dict[str, Any]
    recent_news: list[dict[str, Any]]
    news_status_message: str | None
    sec_event_bundle: SecEventBundle | None
    macro_bundle: FredMacroBundle | None
    alternative_signal_view: AlternativeSignalView
    relative_strength_view: RelativeStrengthView
    earnings_intelligence_view: EarningsIntelligenceView
    history: pd.DataFrame
    enriched_history: pd.DataFrame
    snapshot: dict[str, float | None]
    accounting_quality_view: AccountingQualityView
    long_term_view: LongTermView
    short_term_view: ShortTermView
    long_term_recommendation: LongTermRecommendation
    short_term_recommendation: ShortTermRecommendation
    valuation_summary: str


def _build_valuation_summary(fundamentals: dict[str, Any]) -> str:
    trailing_pe = fundamentals.get("trailingPE")
    forward_pe = fundamentals.get("forwardPE")

    if trailing_pe is None and forward_pe is None:
        return "Valuation data is limited, so the long-term case leans more on trend and operating quality."

    reference_pe = forward_pe if isinstance(forward_pe, (int, float)) else trailing_pe
    if reference_pe is None:
        return "Valuation looks mixed because earnings multiples are incomplete."
    if reference_pe <= 20:
        return "Valuation looks relatively reasonable for a liquid large-cap name."
    if reference_pe <= 32:
        return "Valuation is fair to slightly full, so future returns still need consistent execution."
    return "Valuation is rich, which raises the bar for upside from here."


def _history_to_records(history: pd.DataFrame) -> list[dict[str, Any]]:
    if history.empty:
        return []
    payload = history.reset_index().copy()
    index_column = payload.columns[0]
    payload[index_column] = pd.to_datetime(payload[index_column]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    if index_column != "Date":
        payload = payload.rename(columns={index_column: "Date"})
    return payload.to_dict(orient="records")


def _history_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    history = pd.DataFrame(records)
    if history.empty:
        return history
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history[date_column] = pd.to_datetime(history[date_column]).dt.tz_localize(None)
    if date_column != "Date":
        history = history.rename(columns={date_column: "Date"})
    return history.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]


def _save_live_ticker_cache(
    ticker: str,
    history: pd.DataFrame,
    intraday_15m: pd.DataFrame,
    intraday_60m: pd.DataFrame,
    intraday_source: str,
    fundamentals: dict[str, Any],
    statement_metrics: dict[str, Any],
    quote: dict[str, Any],
    profile: dict[str, Any],
    recent_news: list[dict[str, Any]],
    sec_event_bundle: SecEventBundle | None,
    macro_bundle: FredMacroBundle | None,
    relative_strength_view: RelativeStrengthView,
    earnings_intelligence_view: EarningsIntelligenceView,
) -> str:
    updated_at = datetime.now(timezone.utc).isoformat()
    save_cached_ticker_data(
        ticker,
        {
            "ticker": ticker.upper().strip(),
            "updated_at": updated_at,
            "history": _history_to_records(history),
            "intraday_15m": _history_to_records(intraday_15m),
            "intraday_60m": _history_to_records(intraday_60m),
            "intraday_source": intraday_source,
            "fundamentals": fundamentals,
            "statement_metrics": statement_metrics,
            "quote": quote,
            "profile": profile,
            "recent_news": recent_news,
            "sec_event_bundle": sec_event_bundle.to_dict() if sec_event_bundle else None,
            "macro_bundle": macro_bundle.to_dict() if macro_bundle else None,
            "relative_strength_view": relative_strength_view.to_dict(),
            "earnings_intelligence_view": earnings_intelligence_view.to_dict(),
        },
    )
    return updated_at


def _load_cached_real_ticker(
    ticker: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    str,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    SecEventBundle | None,
    FredMacroBundle | None,
    RelativeStrengthView,
    EarningsIntelligenceView,
    str | None,
]:
    cached = load_cached_ticker_data(ticker)
    if not cached:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            "cached_real",
            {},
            {},
            {},
            {},
            [],
            None,
            None,
            build_unavailable_relative_strength_view(
                sector="N/A",
                message="No cached relative-strength snapshot is available.",
            ),
            build_unavailable_earnings_intelligence_view(
                "No cached earnings-intelligence snapshot is available."
            ),
            None,
        )
    history = _history_from_records(cached.get("history", []))
    intraday_15m = _history_from_records(cached.get("intraday_15m", []))
    intraday_60m = _history_from_records(cached.get("intraday_60m", []))
    fundamentals = cached.get("fundamentals", {})
    if history.empty:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            "cached_real",
            {},
            {},
            {},
            {},
            [],
            None,
            None,
            build_unavailable_relative_strength_view(
                sector=str(fundamentals.get("sector") or "N/A"),
                message="Cached price history is unavailable for relative-strength analysis.",
            ),
            build_unavailable_earnings_intelligence_view(
                "Cached price history is unavailable for earnings intelligence."
            ),
            None,
        )
    return (
        history,
        intraday_15m,
        intraday_60m,
        cached.get("intraday_source", "cached_real"),
        fundamentals,
        cached.get("statement_metrics", {}),
        cached.get("quote", {}),
        cached.get("profile", {}),
        cached.get("recent_news", []),
        sec_event_bundle_from_dict(cached.get("sec_event_bundle")),
        fred_macro_bundle_from_dict(cached.get("macro_bundle")),
        relative_strength_view_from_dict(cached.get("relative_strength_view")),
        earnings_intelligence_view_from_dict(
            cached.get("earnings_intelligence_view")
        ),
        cached.get("updated_at"),
    )


def _combine_messages(*messages: str | None) -> str | None:
    filtered = [message.strip() for message in messages if message and message.strip()]
    if not filtered:
        return None
    return " ".join(dict.fromkeys(filtered))


def _fetch_alternative_sources(ticker: str) -> tuple[SecEventBundle | None, FredMacroBundle | None]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        sec_future = executor.submit(build_sec_edgar_client().get_company_events, ticker)
        macro_future = executor.submit(build_fred_client().get_macro_bundle)
        try:
            sec_bundle = sec_future.result()
        except Exception:
            _log.warning("SEC alternative-signal fetch failed for %s.", ticker, exc_info=True)
            sec_bundle = None
        try:
            macro_bundle = macro_future.result()
        except Exception:
            _log.warning("FRED alternative-signal fetch failed.", exc_info=True)
            macro_bundle = None
    return sec_bundle, macro_bundle


def enrich_relative_strength_with_latest_scan(
    analysis: TickerAnalysis | None,
) -> TickerAnalysis | None:
    if analysis is None or analysis.relative_strength_view.raw_strength_pct is None:
        return analysis
    latest_scan = load_latest_view_scan()
    if not isinstance(latest_scan, dict):
        return analysis
    matching_row = next(
        (
            row
            for row in latest_scan.get("market_rows", [])
            if isinstance(row, dict)
            and str(row.get("ticker") or "").upper().strip() == analysis.ticker
        ),
        None,
    )
    if matching_row is None:
        return analysis
    row_raw_strength = matching_row.get("relative_strength_raw_pct")
    if not isinstance(row_raw_strength, (int, float)):
        return analysis
    if abs(float(row_raw_strength) - float(analysis.relative_strength_view.raw_strength_pct)) > 0.01:
        return analysis

    universe_percentile = matching_row.get("relative_strength_universe_percentile")
    sector_percentile = matching_row.get("relative_strength_sector_percentile")
    analysis.relative_strength_view = replace(
        analysis.relative_strength_view,
        universe_percentile=(
            int(universe_percentile)
            if isinstance(universe_percentile, (int, float))
            else None
        ),
        sector_percentile=(
            int(sector_percentile)
            if isinstance(sector_percentile, (int, float))
            else None
        ),
    )
    return analysis


def _build_analysis(
    ticker: str,
    history: pd.DataFrame,
    intraday_15m: pd.DataFrame,
    intraday_60m: pd.DataFrame,
    intraday_source: str,
    fundamentals: dict[str, Any],
    statement_metrics: dict[str, Any],
    quote: dict[str, Any],
    profile: dict[str, Any],
    recent_news: list[dict[str, Any]],
    sec_event_bundle: SecEventBundle | None,
    macro_bundle: FredMacroBundle | None,
    relative_strength_view: RelativeStrengthView | None,
    earnings_intelligence_view: EarningsIntelligenceView | None,
    intraday_status_message: str | None,
    news_status_message: str | None,
    data_source: str,
    status_message: str | None,
    updated_at: str | None,
) -> TickerAnalysis | None:
    history = apply_quote_to_latest_history(history, quote)
    enriched_history = add_technical_indicators(history)
    merged_fundamentals = merge_profile_into_fundamentals(fundamentals, profile)
    company_name = merged_fundamentals.get("shortName") or ticker.upper().strip()
    sector = str(merged_fundamentals.get("sector") or "N/A")
    if relative_strength_view is None:
        relative_strength_view = build_unavailable_relative_strength_view(
            sector=sector,
            message="Relative-strength analysis is unavailable for this data source.",
        )
    if earnings_intelligence_view is None:
        earnings_intelligence_view = build_unavailable_earnings_intelligence_view(
            "Earnings intelligence is unavailable for this data source."
        )
    news_items = build_news_items(
        recent_news,
        ticker=ticker,
        company_name=str(company_name),
    )
    alternative_signal_view = build_alternative_signal_view(
        sec_bundle=sec_event_bundle,
        news_items=news_items,
        news_status_message=news_status_message,
        macro_bundle=macro_bundle,
    )
    snapshot = build_snapshot(enriched_history, quote=quote)
    if snapshot is None:
        return None

    accounting_quality_view = build_accounting_quality_view(merged_fundamentals, statement_metrics)
    long_term_view = apply_accounting_overlay(
        apply_long_term_news(
            build_long_term_view(enriched_history, merged_fundamentals),
            score_long_term_news(news_items),
        ),
        accounting_quality_view,
    )
    short_term_view = apply_earnings_lockout(
        apply_momentum_context_guard(
            apply_short_term_news(
                build_short_term_view(enriched_history, intraday_15m=intraday_15m, intraday_60m=intraday_60m),
                score_short_term_news(news_items),
            ),
            relative_strength_score=relative_strength_view.score,
            relative_strength_coverage=relative_strength_view.coverage_score,
            hostile_macro_regime=_hostile_macro_regime(macro_bundle),
        ),
        earnings_intelligence_view.days_to_earnings,
    )
    long_rec = build_long_term_recommendation(long_term_view, accounting_quality_view)
    short_rec = build_short_term_recommendation(short_term_view, accounting_quality_view)

    return TickerAnalysis(
        ticker=ticker.upper().strip(),
        company_name=company_name,
        sector=sector,
        data_source=data_source,
        intraday_source=intraday_source,
        status_message=status_message,
        intraday_status_message=intraday_status_message,
        updated_at=updated_at,
        fundamentals=merged_fundamentals,
        statement_metrics=statement_metrics,
        quote=quote,
        profile=profile,
        recent_news=[item.__dict__ for item in news_items],
        news_status_message=news_status_message,
        sec_event_bundle=sec_event_bundle,
        macro_bundle=macro_bundle,
        alternative_signal_view=alternative_signal_view,
        relative_strength_view=relative_strength_view,
        earnings_intelligence_view=earnings_intelligence_view,
        history=history,
        enriched_history=enriched_history,
        snapshot=snapshot,
        accounting_quality_view=accounting_quality_view,
        long_term_view=long_term_view,
        short_term_view=short_term_view,
        long_term_recommendation=long_rec,
        short_term_recommendation=short_rec,
        valuation_summary=_build_valuation_summary(fundamentals),
    )


def build_ticker_analysis(ticker: str, data_mode: str = DATA_MODE_AUTO) -> TickerAnalysis | None:
    normalized_ticker = ticker.upper().strip()

    if data_mode == DATA_MODE_DEMO:
        demo_data = load_demo_stock_data(normalized_ticker)
        if demo_data is None:
            return None
        history, fundamentals = demo_data
        return _build_analysis(
            normalized_ticker,
            history,
            pd.DataFrame(),
            pd.DataFrame(),
            "demo",
            fundamentals,
            {},
            quote={},
            profile={},
            recent_news=[],
            sec_event_bundle=None,
            macro_bundle=None,
            relative_strength_view=None,
            earnings_intelligence_view=None,
            intraday_status_message="Intraday analysis is not live in demo mode.",
            news_status_message="Finnhub news is not used in demo mode.",
            data_source="demo",
            status_message="Using demo data for testing.",
            updated_at=None,
        )

    live_history, live_fundamentals, live_source, live_message = load_market_data(normalized_ticker, mode=DATA_MODE_LIVE)
    if live_source == "live" and not live_history.empty:
        intraday_15m, intraday_60m, intraday_message = fetch_live_intraday_data(normalized_ticker)
        intraday_source = "live" if not intraday_15m.empty or not intraday_60m.empty else "unavailable"
        statement_metrics = fetch_financial_statement_metrics(normalized_ticker)
        finnhub_bundle, finnhub_message = fetch_finnhub_bundle(normalized_ticker)
        sec_event_bundle, macro_bundle = _fetch_alternative_sources(normalized_ticker)
        merged_fundamentals = merge_profile_into_fundamentals(
            live_fundamentals,
            finnhub_bundle.get("profile", {}),
        )
        sector = str(merged_fundamentals.get("sector") or "N/A")
        benchmarks = load_relative_strength_benchmarks(sector)
        relative_strength_view = build_relative_strength_view(
            stock_history=live_history,
            market_history=benchmarks.market_history,
            sector_history=benchmarks.sector_history,
            sector=sector,
            market_symbol=benchmarks.market_symbol,
            sector_symbol=benchmarks.sector_symbol,
            warning=benchmarks.message,
        )
        earnings_context = fetch_earnings_estimate_context(normalized_ticker)
        earnings_history = finnhub_bundle.get("earnings_history", [])
        earnings_history = (
            earnings_history if isinstance(earnings_history, list) else []
        )
        earnings_news_items = build_news_items(
            finnhub_bundle.get("news", []),
            ticker=normalized_ticker,
            company_name=str(
                merged_fundamentals.get("shortName") or normalized_ticker
            ),
        )
        earnings_intelligence_view = build_earnings_intelligence_view(
            stock_history=live_history,
            earnings_history=earnings_history,
            estimate_context=earnings_context,
            sec_bundle=sec_event_bundle,
            news_items=earnings_news_items,
            warning=(
                finnhub_message
                if not earnings_history and finnhub_message
                else None
            ),
        )
        updated_at = _save_live_ticker_cache(
            normalized_ticker,
            live_history,
            intraday_15m,
            intraday_60m,
            intraday_source,
            live_fundamentals,
            statement_metrics,
            finnhub_bundle.get("quote", {}),
            finnhub_bundle.get("profile", {}),
            finnhub_bundle.get("news", []),
            sec_event_bundle,
            macro_bundle,
            relative_strength_view,
            earnings_intelligence_view,
        )
        return _build_analysis(
            normalized_ticker,
            live_history,
            intraday_15m,
            intraday_60m,
            intraday_source,
            live_fundamentals,
            statement_metrics,
            quote=finnhub_bundle.get("quote", {}),
            profile=finnhub_bundle.get("profile", {}),
            recent_news=finnhub_bundle.get("news", []),
            sec_event_bundle=sec_event_bundle,
            macro_bundle=macro_bundle,
            relative_strength_view=relative_strength_view,
            earnings_intelligence_view=earnings_intelligence_view,
            intraday_status_message=intraday_message,
            news_status_message=finnhub_message,
            data_source="live",
            status_message=_combine_messages(live_message, intraday_message, finnhub_message),
            updated_at=updated_at,
        )

    if data_mode == DATA_MODE_LIVE:
        return None

    (
        cached_history,
        cached_15m,
        cached_60m,
        cached_intraday_source,
        cached_fundamentals,
        cached_statement_metrics,
        cached_quote,
        cached_profile,
        cached_recent_news,
        cached_sec_event_bundle,
        cached_macro_bundle,
        cached_relative_strength_view,
        cached_earnings_intelligence_view,
        cached_updated_at,
    ) = _load_cached_real_ticker(normalized_ticker)
    if not cached_history.empty:
        return _build_analysis(
            normalized_ticker,
            cached_history,
            cached_15m,
            cached_60m,
            cached_intraday_source,
            cached_fundamentals,
            cached_statement_metrics,
            quote=cached_quote,
            profile=cached_profile,
            recent_news=cached_recent_news,
            sec_event_bundle=cached_sec_event_bundle,
            macro_bundle=cached_macro_bundle,
            relative_strength_view=cached_relative_strength_view,
            earnings_intelligence_view=cached_earnings_intelligence_view,
            intraday_status_message="Using cached intraday data where available.",
            news_status_message="Using cached Finnhub news and market context where available.",
            data_source="cached_real",
            status_message="Using cached real data because live data is unavailable. Recommendations may be stale.",
            updated_at=cached_updated_at,
        )

    if ALLOW_DEMO_FALLBACK:
        demo_data = load_demo_stock_data(normalized_ticker)
        if demo_data is not None:
            history, fundamentals = demo_data
            return _build_analysis(
                normalized_ticker,
                history,
                pd.DataFrame(),
                pd.DataFrame(),
                "demo",
                fundamentals,
                {},
                quote={},
                profile={},
                recent_news=[],
                sec_event_bundle=None,
                macro_bundle=None,
                relative_strength_view=None,
                earnings_intelligence_view=None,
                intraday_status_message="Intraday analysis is not live in demo mode.",
                news_status_message="Finnhub news is not used in demo mode.",
                data_source="demo",
                status_message="Using demo data because live and cached real data are unavailable.",
                updated_at=None,
            )

    return None
