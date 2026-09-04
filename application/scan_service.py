from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from application.long_term_outcome_evaluation_service import LongTermOutcomeEvaluationService
from application.long_term_signal_log_service import LongTermSignalLogService
from application.outcome_evaluation_service import OutcomeEvaluationService
from application.signal_log_service import SignalLogService
from application.ticker_service import TickerAnalysis, build_ticker_analysis
from config.settings import ALLOW_DEMO_FALLBACK, DATA_MODE_AUTO, DATA_MODE_DEMO, DATA_MODE_LIVE
from config.universe import DEFAULT_STOCK_UNIVERSE, DEFAULT_UNIVERSE_NAME, universe_filters_for_ticker
from domain.signals.freshness import apply_scan_freshness_policy
from storage.repositories.scan_repository import load_named_scan_cache, save_latest_view_scan, save_named_scan_cache


_log = logging.getLogger(__name__)
_SCAN_WORKERS = 8

signal_log_service = SignalLogService()
long_term_signal_log_service = LongTermSignalLogService()
outcome_evaluation_service = OutcomeEvaluationService()
long_term_outcome_evaluation_service = LongTermOutcomeEvaluationService()


def _relative_strength_fields(result: TickerAnalysis) -> dict[str, Any]:
    view = result.relative_strength_view
    periods = {period.key: period for period in view.periods}
    six_month = periods.get("6m")
    return {
        "relative_strength_score": view.score,
        "relative_strength_status": view.status,
        "relative_strength_coverage": view.coverage_score,
        "relative_strength_applied_impact": view.applied_impact,
        "relative_strength_raw_pct": view.raw_strength_pct,
        "market_relative_pct": view.market_relative_pct,
        "sector_relative_pct": view.sector_relative_pct,
        "sector_leadership_pct": view.sector_leadership_pct,
        "relative_strength_universe_percentile": view.universe_percentile,
        "relative_strength_sector_percentile": view.sector_percentile,
        "market_benchmark_symbol": view.market_benchmark_symbol,
        "sector_benchmark_symbol": view.sector_benchmark_symbol,
        "market_excess_6m_pct": six_month.market_excess_pct if six_month else None,
        "sector_excess_6m_pct": six_month.sector_excess_pct if six_month else None,
    }


def _earnings_intelligence_fields(result: TickerAnalysis) -> dict[str, Any]:
    view = result.earnings_intelligence_view
    return {
        "earnings_intelligence_score": view.score,
        "earnings_intelligence_status": view.status,
        "earnings_intelligence_coverage": view.coverage_score,
        "earnings_intelligence_applied_impact": view.applied_impact,
        "next_earnings_date": view.next_earnings_date,
        "days_to_earnings": view.days_to_earnings,
        "earnings_event_risk": view.event_risk,
        "latest_eps_surprise_pct": view.latest_surprise_pct,
        "average_eps_surprise_pct": view.average_surprise_pct,
        "eps_beat_rate_pct": view.beat_rate_pct,
        "eps_consecutive_beats": view.consecutive_beats,
        "eps_surprise_trend": view.surprise_trend,
        "current_quarter_eps_growth_pct": view.current_quarter_growth_pct,
        "net_eps_revisions_30d": view.net_revisions_30d,
        "post_earnings_filing_3d_return_pct": view.post_filing_3d_return_pct,
    }


def _passes_universe_filters(result: TickerAnalysis) -> bool:
    filters = universe_filters_for_ticker(result.ticker)
    price = result.snapshot["current_price"] or 0
    avg_volume = result.snapshot["avg_volume_20"] or 0
    market_cap = result.fundamentals.get("marketCap") or 0
    min_history_points = filters.min_history_points if result.data_source != "demo" else min(120, filters.min_history_points)
    volume_ok = avg_volume >= filters.min_average_volume
    market_cap_ok = filters.min_market_cap <= 0 or market_cap >= filters.min_market_cap
    return (
        len(result.enriched_history) >= min_history_points
        and price >= filters.min_price
        and volume_ok
        and market_cap_ok
    )


def _build_market_row(result: TickerAnalysis) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "data_source": result.data_source,
        "updated_at": result.updated_at,
        "daily_change_pct": round(float(result.snapshot["daily_change_pct"]), 2),
        "long_term_score": result.long_term_view.score,
        "short_term_score": result.short_term_view.score,
        "short_term_regime": result.short_term_view.primary_regime_label,
        "trend_direction": result.short_term_view.trend_direction,
        "trade_state": result.short_term_view.trade_state_label,
        "rsi": round(float(result.snapshot["rsi"]), 2) if result.snapshot["rsi"] is not None else None,
        "alternative_signal_score": result.alternative_signal_view.score,
        "alternative_signal_modeled_impact": result.alternative_signal_view.modeled_impact,
        "alternative_signal_coverage": result.alternative_signal_view.coverage_score,
        **_relative_strength_fields(result),
        **_earnings_intelligence_fields(result),
    }


def _build_long_term_row(result: TickerAnalysis) -> dict[str, Any]:
    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "sector": result.sector,
        "data_source": result.data_source,
        "updated_at": result.updated_at,
        "long_term_score": result.long_term_view.score,
        "trend_factor": result.long_term_view.trend_factor,
        "quality_factor": result.long_term_view.quality_factor,
        "growth_factor": result.long_term_view.growth_factor,
        "valuation_factor": result.long_term_view.valuation_factor,
        "balance_sheet_factor": result.long_term_view.balance_sheet_factor,
        "factor_points": result.long_term_view.factor_points,
        "factor_weights": result.long_term_view.factor_weights,
        "recommendation_label": result.long_term_recommendation.label,
        "confidence": result.long_term_recommendation.confidence,
        "tone": result.long_term_recommendation.tone,
        "valuation_summary": result.valuation_summary,
        "key_strengths": result.long_term_recommendation.reasons[:3],
        "key_risks": result.long_term_recommendation.risks[:2],
        "thesis": result.long_term_recommendation.thesis,
        "summary_reasoning": result.long_term_view.summary,
        "market_cap": result.fundamentals.get("marketCap"),
        "news_score": result.long_term_view.news_score,
        "news_effect": result.long_term_recommendation.news_effect,
        "alternative_signal_score": result.alternative_signal_view.score,
        "alternative_signal_modeled_impact": result.alternative_signal_view.modeled_impact,
        "alternative_signal_applied_impact": result.alternative_signal_view.applied_impact,
        "alternative_signal_coverage": result.alternative_signal_view.coverage_score,
        "alternative_signal_status": result.alternative_signal_view.status,
        **_relative_strength_fields(result),
        **_earnings_intelligence_fields(result),
        "accounting_quality_score": result.accounting_quality_view.accounting_quality_score,
        "shenanigan_risk_score": result.accounting_quality_view.shenanigan_risk_score,
        "accounting_data_completeness_score": result.accounting_quality_view.accounting_data_completeness_score,
        "accounting_assessment_confidence": result.accounting_quality_view.accounting_assessment_confidence,
        "accounting_label": result.accounting_quality_view.label,
        "accounting_explanation": result.accounting_quality_view.explanation,
        "accounting_limitations_note": result.accounting_quality_view.limitations_note,
        "accounting_red_flags": result.accounting_quality_view.red_flags[:3],
    }


def _build_short_term_row(result: TickerAnalysis) -> dict[str, Any]:
    day_trade = result.short_term_view.day_trade
    swing_trade = result.short_term_view.swing_trade
    primary_trade = day_trade if result.short_term_view.primary_horizon_label == day_trade.horizon_label else swing_trade
    return {
        "ticker": result.ticker,
        "company_name": result.company_name,
        "sector": result.sector,
        "data_source": result.data_source,
        "updated_at": result.updated_at,
        "short_term_score": result.short_term_view.score,
        "recommendation_label": result.short_term_recommendation.label,
        "confidence": result.short_term_recommendation.confidence,
        "tone": result.short_term_recommendation.tone,
        "setup_type": result.short_term_recommendation.setup_type,
        "setup_regime": result.short_term_view.primary_regime_label,
        "ranking_bucket": result.short_term_view.primary_ranking_bucket,
        "regime_scores": result.short_term_view.regime_scores,
        "entry": result.short_term_recommendation.entry_idea,
        "stop_loss": result.short_term_recommendation.stop_loss_idea,
        "target": result.short_term_recommendation.target_idea,
        "entry_price": primary_trade.entry_price,
        "target_price": primary_trade.target_price,
        "stop_loss_price": primary_trade.stop_loss_price,
        "current_price": result.snapshot.get("current_price"),
        "primary_horizon_label": result.short_term_view.primary_horizon_label,
        "reasons": result.short_term_recommendation.reasons[:3],
        "invalidation_note": result.short_term_recommendation.invalidation_note,
        "expected_holding_period": result.short_term_recommendation.expected_holding_period,
        "trend_direction": result.short_term_view.trend_direction,
        "trade_state": result.short_term_view.trade_state_label,
        "trade_state_tone": result.short_term_view.trade_state_tone,
        "trade_state_explanation": result.short_term_view.trade_state_explanation,
        "breakout_level": result.short_term_view.breakout_level,
        "breakdown_level": result.short_term_view.breakdown_level,
        "is_actionable_now": result.short_term_view.is_actionable_now,
        "news_score": result.short_term_view.news_score,
        "news_effect": result.short_term_recommendation.news_effect,
        "alternative_signal_score": result.alternative_signal_view.score,
        "alternative_signal_modeled_impact": result.alternative_signal_view.modeled_impact,
        "alternative_signal_applied_impact": result.alternative_signal_view.applied_impact,
        "alternative_signal_coverage": result.alternative_signal_view.coverage_score,
        "alternative_signal_status": result.alternative_signal_view.status,
        **_relative_strength_fields(result),
        **_earnings_intelligence_fields(result),
        "accounting_warning": result.short_term_recommendation.accounting_warning,
        "accounting_label": result.accounting_quality_view.label,
        "shenanigan_risk_score": result.accounting_quality_view.shenanigan_risk_score,
        "accounting_data_completeness_score": result.accounting_quality_view.accounting_data_completeness_score,
        "accounting_assessment_confidence": result.accounting_quality_view.accounting_assessment_confidence,
        "day_trade": {
            "label": day_trade.horizon_label,
            "score": day_trade.score,
            "trade_state": day_trade.trade_state_label,
            "trade_state_tone": day_trade.trade_state_tone,
            "holding_period": day_trade.holding_period_label,
            "setup_type": day_trade.setup_type,
            "regime": day_trade.regime_label,
            "regime_scores": day_trade.regime_scores,
            "ranking_bucket": day_trade.ranking_bucket,
            "entry_price": day_trade.entry_price,
            "target_price": day_trade.target_price,
            "stop_loss_price": day_trade.stop_loss_price,
            "explanation": day_trade.explanation,
        },
        "swing_trade": {
            "label": swing_trade.horizon_label,
            "score": swing_trade.score,
            "trade_state": swing_trade.trade_state_label,
            "trade_state_tone": swing_trade.trade_state_tone,
            "holding_period": swing_trade.holding_period_label,
            "setup_type": swing_trade.setup_type,
            "regime": swing_trade.regime_label,
            "regime_scores": swing_trade.regime_scores,
            "ranking_bucket": swing_trade.ranking_bucket,
            "entry_price": swing_trade.entry_price,
            "target_price": swing_trade.target_price,
            "stop_loss_price": swing_trade.stop_loss_price,
            "explanation": swing_trade.explanation,
        },
    }


def _build_market_stats(
    market_rows: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
    universe_size: int,
) -> dict[str, Any]:
    if not market_rows:
        return {
            "universe_size": universe_size,
            "scanned_count": 0,
            "advancers": 0,
            "decliners": 0,
            "avg_long_term_score": None,
            "avg_short_term_score": None,
            "bullish_setups": 0,
            "fallback_count": 0,
            "recommendation_count": 0,
            "avg_relative_strength_score": None,
            "relative_strength_leaders": 0,
            "relative_strength_laggards": 0,
            "avg_earnings_intelligence_score": None,
            "earnings_event_risk_count": 0,
            "earnings_strong_count": 0,
            "earnings_caution_count": 0,
        }

    advancers = sum(1 for row in market_rows if row["daily_change_pct"] >= 0)
    decliners = len(market_rows) - advancers
    avg_long = sum(row["long_term_score"] for row in market_rows) / len(market_rows)
    avg_short = sum(row["short_term_score"] for row in market_rows) / len(market_rows)
    bullish = sum(1 for row in short_rows if row["trend_direction"] == "Bullish")
    fallback_count = sum(1 for row in market_rows if row.get("data_source") != "live")
    relative_scores = [
        int(row["relative_strength_score"])
        for row in market_rows
        if isinstance(row.get("relative_strength_score"), (int, float))
    ]
    earnings_scores = [
        int(row["earnings_intelligence_score"])
        for row in market_rows
        if isinstance(row.get("earnings_intelligence_score"), (int, float))
    ]
    return {
        "universe_size": universe_size,
        "scanned_count": len(market_rows),
        "advancers": advancers,
        "decliners": decliners,
        "avg_long_term_score": round(avg_long, 1),
        "avg_short_term_score": round(avg_short, 1),
        "bullish_setups": bullish,
        "long_candidates": len(long_rows),
        "short_candidates": len(short_rows),
        "fallback_count": fallback_count,
        "recommendation_count": len(long_rows) + len(short_rows),
        "avg_relative_strength_score": (
            round(sum(relative_scores) / len(relative_scores), 1)
            if relative_scores
            else None
        ),
        "relative_strength_leaders": sum(
            int(row.get("relative_strength_score") or 0) >= 70
            and int(row.get("relative_strength_coverage") or 0) >= 70
            for row in market_rows
        ),
        "relative_strength_laggards": sum(
            isinstance(row.get("relative_strength_score"), (int, float))
            and int(row["relative_strength_score"]) <= 30
            and int(row.get("relative_strength_coverage") or 0) >= 70
            for row in market_rows
        ),
        "avg_earnings_intelligence_score": (
            round(sum(earnings_scores) / len(earnings_scores), 1)
            if earnings_scores
            else None
        ),
        "earnings_event_risk_count": sum(
            row.get("earnings_event_risk") in {"high", "elevated"}
            for row in market_rows
        ),
        "earnings_strong_count": sum(
            isinstance(row.get("earnings_intelligence_score"), (int, float))
            and int(row["earnings_intelligence_score"]) >= 70
            and int(row.get("earnings_intelligence_coverage") or 0) >= 60
            for row in market_rows
        ),
        "earnings_caution_count": sum(
            isinstance(row.get("earnings_intelligence_score"), (int, float))
            and int(row["earnings_intelligence_score"]) <= 42
            and int(row.get("earnings_intelligence_coverage") or 0) >= 60
            for row in market_rows
        ),
    }


def _assign_short_regime_ranks(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = str(row.get("ranking_bucket") or row.get("setup_regime") or "UNKNOWN")
        buckets.setdefault(bucket, []).append(row)

    for bucket, bucket_rows in buckets.items():
        bucket_rows.sort(
            key=lambda row: (
                float(row.get("short_term_score") or 0.0),
                str(row.get("ticker") or ""),
            ),
            reverse=True,
        )
        for index, row in enumerate(bucket_rows, start=1):
            row["rank_within_regime"] = index
            row["regime_peer_count"] = len(bucket_rows)
            row["regime_rank_label"] = f"{index}/{len(bucket_rows)} in {bucket}"
    return rows


def _percentile_rank(value: float, values: list[float], *, minimum_peers: int) -> int | None:
    if len(values) < minimum_peers:
        return None
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    denominator = len(values) - 1
    if denominator <= 0:
        return None
    mid_rank = below + (equal - 1) / 2
    return int(round(mid_rank / denominator * 100))


def _assign_relative_strength_percentiles(results: list[TickerAnalysis]) -> None:
    valid_results = [
        result
        for result in results
        if result.relative_strength_view.raw_strength_pct is not None
        and result.relative_strength_view.coverage_score >= 40
    ]
    universe_values = [
        float(result.relative_strength_view.raw_strength_pct)
        for result in valid_results
        if result.relative_strength_view.raw_strength_pct is not None
    ]
    sector_values: dict[str, list[float]] = {}
    for result in valid_results:
        sector_values.setdefault(result.sector, []).append(
            float(result.relative_strength_view.raw_strength_pct)
        )

    for result in valid_results:
        raw_strength = float(result.relative_strength_view.raw_strength_pct)
        result.relative_strength_view = replace(
            result.relative_strength_view,
            universe_percentile=_percentile_rank(
                raw_strength,
                universe_values,
                minimum_peers=5,
            ),
            sector_percentile=_percentile_rank(
                raw_strength,
                sector_values.get(result.sector, []),
                minimum_peers=3,
            ),
        )


def _build_scan_payload(
    source: str,
    tickers: list[str],
    market_rows: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
    failures: list[str],
    universe_name: str,
    universe_size: int,
    updated_at: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    payload = {
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "source": source,
        "universe_name": universe_name,
        "universe": tickers,
        "market_stats": _build_market_stats(market_rows, long_rows, short_rows, universe_size),
        "long_term": long_rows,
        "short_term": short_rows,
        "market_rows": market_rows,
        "failures": failures,
    }
    if message:
        payload["message"] = message
    return apply_scan_freshness_policy(payload)


def _rank_results(results: list[TickerAnalysis]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    market_rows: list[dict[str, Any]] = []
    long_rows: list[dict[str, Any]] = []
    short_rows: list[dict[str, Any]] = []

    for result in results:
        if not _passes_universe_filters(result):
            continue
        market_rows.append(_build_market_row(result))
        long_rows.append(_build_long_term_row(result))
        short_rows.append(_build_short_term_row(result))

    long_rows.sort(key=lambda row: row["long_term_score"], reverse=True)
    short_rows.sort(key=lambda row: row["short_term_score"], reverse=True)
    short_rows = _assign_short_regime_ranks(short_rows)
    return market_rows, long_rows, short_rows


def _run_scan_for_mode(tickers: list[str], data_mode: str) -> tuple[list[TickerAnalysis], list[str]]:
    """Run per-ticker analyses in parallel.

    `build_ticker_analysis` is I/O bound (yfinance + Finnhub HTTP) so a thread
    pool gives near-linear speedup until provider rate limits dominate. Eight
    workers is a conservative cap that keeps Finnhub well under its 60 req/s
    free-tier limit and avoids overwhelming the host with subprocess threads.
    Results are returned in the original ticker order so downstream ranking
    and presentation stay deterministic across runs.

    SQLite writes (signal_log_service.log_scan_analyses) are intentionally
    NOT parallelised — they run sequentially in the caller after this returns.
    """
    if not tickers:
        return [], []

    indexed_results: list[tuple[int, TickerAnalysis]] = []
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as executor:
        future_to_index = {
            executor.submit(build_ticker_analysis, ticker, data_mode=data_mode): (index, ticker)
            for index, ticker in enumerate(tickers)
        }
        for future in as_completed(future_to_index):
            index, ticker = future_to_index[future]
            try:
                analysis = future.result()
            except Exception:
                _log.error(
                    "build_ticker_analysis raised for %s in mode %s; treating as failure.",
                    ticker,
                    data_mode,
                    exc_info=True,
                )
                failures.append(ticker)
                continue
            if analysis is None:
                failures.append(ticker)
                continue
            indexed_results.append((index, analysis))

    indexed_results.sort(key=lambda pair: pair[0])
    results = [analysis for _, analysis in indexed_results]
    _assign_relative_strength_percentiles(results)
    return results, failures


def _cached_real_payload(tickers: list[str], universe_name: str, cache_key: str) -> dict[str, Any] | None:
    cached = load_named_scan_cache(cache_key)
    if not cached:
        return None
    cached = dict(cached)
    scan_updated_at = cached.get("updated_at")
    cached["market_rows"] = [{**row, "data_source": "cached_real", "updated_at": row.get("updated_at") or scan_updated_at} for row in cached.get("market_rows", [])]
    cached["long_term"] = [{**row, "data_source": "cached_real", "updated_at": row.get("updated_at") or scan_updated_at} for row in cached.get("long_term", [])]
    cached["short_term"] = [{**row, "data_source": "cached_real", "updated_at": row.get("updated_at") or scan_updated_at} for row in cached.get("short_term", [])]
    cached["source"] = "cached_real"
    cached["universe"] = tickers
    cached["universe_name"] = universe_name
    cached["message"] = "Using cached real data because live data is unavailable. Stale signals are read-only."
    cached["market_stats"] = _build_market_stats(cached["market_rows"], cached["long_term"], cached["short_term"], len(tickers))
    cached = apply_scan_freshness_policy(cached, source_override="cached_real")
    save_latest_view_scan(cached)
    return cached


def run_scan(
    universe: list[str] | None = None,
    data_mode: str = DATA_MODE_AUTO,
    universe_name: str = DEFAULT_UNIVERSE_NAME,
    cache_key: str = "default",
) -> dict[str, Any]:
    tickers = universe or DEFAULT_STOCK_UNIVERSE

    if data_mode == DATA_MODE_DEMO:
        demo_results, demo_failures = _run_scan_for_mode(tickers, DATA_MODE_DEMO)
        market_rows, long_rows, short_rows = _rank_results(demo_results)
        payload = _build_scan_payload(
            source="demo",
            tickers=tickers,
            market_rows=market_rows,
            long_rows=long_rows,
            short_rows=short_rows,
            failures=demo_failures,
            universe_name=universe_name,
            universe_size=len(tickers),
            message="Using demo data because this mode is intended for testing.",
        )
        save_latest_view_scan(payload)
        return payload

    live_results, live_failures = _run_scan_for_mode(tickers, DATA_MODE_LIVE)
    if live_results:
        signal_log_service.log_scan_analyses(live_results)
        long_term_signal_log_service.log_scan_analyses(live_results)
        outcome_evaluation_service.evaluate_open_short_term_signals()
        long_term_outcome_evaluation_service.evaluate_open_long_term_signals()
        market_rows, long_rows, short_rows = _rank_results(live_results)
        payload = _build_scan_payload(
            source="live",
            tickers=tickers,
            market_rows=market_rows,
            long_rows=long_rows,
            short_rows=short_rows,
            failures=live_failures,
            universe_name=universe_name,
            universe_size=len(tickers),
        )
        save_named_scan_cache(cache_key, payload)
        save_latest_view_scan(payload)
        return payload

    cached_payload = _cached_real_payload(tickers, universe_name, cache_key)
    if cached_payload is not None:
        outcome_evaluation_service.evaluate_open_short_term_signals()
        long_term_outcome_evaluation_service.evaluate_open_long_term_signals()
        return cached_payload

    if ALLOW_DEMO_FALLBACK:
        demo_results, demo_failures = _run_scan_for_mode(tickers, DATA_MODE_DEMO)
        outcome_evaluation_service.evaluate_open_short_term_signals()
        long_term_outcome_evaluation_service.evaluate_open_long_term_signals()
        market_rows, long_rows, short_rows = _rank_results(demo_results)
        payload = _build_scan_payload(
            source="demo",
            tickers=tickers,
            market_rows=market_rows,
            long_rows=long_rows,
            short_rows=short_rows,
            failures=live_failures + demo_failures,
            universe_name=universe_name,
            universe_size=len(tickers),
            message="Using demo data because live and cached real data are unavailable.",
        )
        save_latest_view_scan(payload)
        return payload

    payload = _build_scan_payload(
        source="unavailable",
        tickers=tickers,
        market_rows=[],
        long_rows=[],
        short_rows=[],
        failures=live_failures,
        universe_name=universe_name,
        universe_size=len(tickers),
        message="No market data is available right now.",
    )
    outcome_evaluation_service.evaluate_open_short_term_signals()
    long_term_outcome_evaluation_service.evaluate_open_long_term_signals()
    save_latest_view_scan(payload)
    return payload
