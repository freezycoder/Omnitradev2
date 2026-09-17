from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from application.etf_signal_service import log_etf_signals
from config.etf import (
    DEFAULT_ETF_UNIVERSE,
    ETF_SCREENER_CACHE_KEY,
    ETF_SCREENER_PAGE_SIZE,
    ETF_UNIVERSE_NAME,
    MIN_ETF_EXPOSURE_WEIGHT,
    EtfUniverseFilters,
)
from domain.assets import AssetType
from domain.etf.exposure import UnderlyingSignalExposure, reverse_etf_exposure, thematic_exposure_score
from domain.etf.metrics import aligned_correlation, build_performance_metrics
from domain.etf.models import DATA_UNAVAILABLE, EtfHoldingsSnapshot, EtfProfile
from domain.etf.overlap import allocation_compare, pairwise_overlap, profile_compare_row, shared_and_unique
from domain.recommendations.engine import build_short_term_recommendation
from domain.scoring.etf import build_etf_omni_score
from domain.scoring.short_term import build_short_term_view
from domain.technical.indicators import add_technical_indicators
from providers.etf.composite import CompositeEtfProvider, build_etf_provider
from providers.market.market_provider import fetch_price_histories, fetch_price_history
from storage.repositories.etf_repository import EtfRepository
from storage.repositories.scan_repository import load_named_scan_cache, save_named_scan_cache


EQUITY_QUOTE_TYPES = {"ETF", "MUTUALFUND", "INDEX", "FUND"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _history_records(history: pd.DataFrame) -> list[dict[str, Any]]:
    if history is None or history.empty:
        return []
    payload = history.reset_index().copy()
    index_column = payload.columns[0]
    payload[index_column] = pd.to_datetime(payload[index_column]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    if index_column != "Date":
        payload = payload.rename(columns={index_column: "Date"})
    return payload.to_dict(orient="records")


def _is_etf_profile(profile: EtfProfile | None, ticker: str) -> bool:
    if profile is None:
        return ticker.upper() in DEFAULT_ETF_UNIVERSE
    quote_type = (profile.quote_type or "").upper()
    asset_class = (profile.asset_class or "").upper()
    if ticker.upper() in DEFAULT_ETF_UNIVERSE:
        return True
    if quote_type in EQUITY_QUOTE_TYPES or "ETF" in asset_class or "FUND" in asset_class:
        return True
    return False


class EtfService:
    def __init__(
        self,
        repository: EtfRepository | None = None,
        provider: CompositeEtfProvider | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._repository = repository or EtfRepository(db_path)
        self._provider = provider or build_etf_provider()

    def get_profile(self, ticker: str, *, refresh: bool = False) -> EtfProfile | None:
        normalized = ticker.upper().strip()
        if not refresh:
            cached = self._repository.get_profile(normalized, require_fresh=True)
            if cached is not None:
                return cached
        profile = self._provider.get_profile(normalized)
        if profile is not None:
            self._repository.upsert_profile(profile)
        return profile

    def get_holdings(self, ticker: str, *, refresh: bool = False) -> EtfHoldingsSnapshot | None:
        normalized = ticker.upper().strip()
        if not refresh:
            cached = self._repository.get_holdings(normalized, require_fresh=True)
            if cached is not None:
                return cached
        snapshot = self._provider.get_holdings(normalized)
        if snapshot is not None and snapshot.holdings:
            self._repository.replace_holdings(snapshot)
            profile = self._repository.get_profile(normalized)
            if profile is not None and (profile.holdings_count is None or not profile.sector_exposure):
                self._repository.upsert_profile(
                    EtfProfile(
                        ticker=profile.ticker,
                        name=profile.name,
                        issuer=profile.issuer,
                        asset_class=profile.asset_class,
                        category=profile.category,
                        description=profile.description,
                        expense_ratio=profile.expense_ratio,
                        aum=profile.aum,
                        average_volume=profile.average_volume,
                        dividend_yield=profile.dividend_yield,
                        inception_date=profile.inception_date,
                        holdings_count=profile.holdings_count or snapshot.holdings_count,
                        geographic_exposure=snapshot.geographic_allocation or profile.geographic_exposure,
                        sector_exposure=snapshot.sector_allocation or profile.sector_exposure,
                        source=profile.source,
                        quote_type=profile.quote_type,
                        updated_at=profile.updated_at,
                        unavailable_fields=profile.unavailable_fields,
                    )
                )
        return snapshot

    def search(self, filters: EtfUniverseFilters, *, offset: int = 0, limit: int = ETF_SCREENER_PAGE_SIZE) -> dict[str, Any]:
        universe = DEFAULT_ETF_UNIVERSE
        profiles = self._repository.list_profiles(filters=filters, tickers=universe)
        if filters.ticker:
            extra = filters.ticker.upper().strip()
            if extra and extra not in {profile.ticker for profile in profiles}:
                profile = self.get_profile(extra)
                if profile is not None and _is_etf_profile(profile, extra):
                    profiles = [*profiles, profile]
        total = len(profiles)
        page = profiles[offset : offset + limit]
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "results": [profile.to_dict() for profile in page],
        }

    def empty_screener(self, *, message: str, refresh_status: str = "idle") -> dict[str, Any]:
        return {
            "updated_at": None,
            "source": "unavailable",
            "universe_name": ETF_UNIVERSE_NAME,
            "universe": list(DEFAULT_ETF_UNIVERSE),
            "asset_type": AssetType.ETF,
            "rows": [],
            "failures": [],
            "filtered_count": 0,
            "note": "ETF OmniScore is a research composite and is not a validated forecast.",
            "refresh_status": refresh_status,
            "api_note": message,
        }

    def cached_screener(self, filters: EtfUniverseFilters | None = None) -> dict[str, Any] | None:
        cached = load_named_scan_cache(ETF_SCREENER_CACHE_KEY)
        if not cached:
            return None
        return self._filter_screener(cached, filters)

    def build_screener(
        self,
        filters: EtfUniverseFilters | None = None,
        *,
        refresh: bool = False,
        log_signals: bool = False,
    ) -> dict[str, Any]:
        if not refresh:
            cached = self.cached_screener(filters)
            if cached:
                return {**cached, "refresh_status": cached.get("refresh_status") or "idle"}
            return self.empty_screener(
                message="No ETF rows are cached yet. Use Refresh cache to pull provider data in the background."
            )

        tickers = list(DEFAULT_ETF_UNIVERSE)
        profiles = []
        failures: list[str] = []
        for ticker in tickers:
            try:
                profile = self.get_profile(ticker, refresh=True)
            except Exception:
                profile = None
                failures.append(f"{ticker}: profile unavailable")
            if profile is None:
                failures.append(f"{ticker}: profile unavailable")
                continue
            profiles.append(profile)
        histories = fetch_price_histories(tickers, period="2y")
        stock_scores = load_stock_signal_scores()
        rows: list[dict[str, Any]] = []
        analyses_for_signals: list[dict[str, Any]] = []
        for profile in profiles:
            history = histories.get(profile.ticker, pd.DataFrame())
            metrics = build_performance_metrics(history)
            # Screener uses cached holdings only. Live holdings stay on the analysis page
            # so a 40-ETF universe refresh can finish without one yfinance scrape per fund.
            holdings = self._repository.get_holdings(profile.ticker, require_fresh=False)
            underlying_score, coverage, _contributors = thematic_exposure_score(
                holdings.holdings if holdings else (),
                stock_scores,
            )
            omni = build_etf_omni_score(
                profile,
                metrics,
                holdings,
                underlying_exposure_score=underlying_score,
                underlying_coverage_weight=coverage,
            )
            row = {
                "ticker": profile.ticker,
                "asset_type": AssetType.ETF,
                "name": profile.name,
                "category": profile.category,
                "issuer": profile.issuer,
                "asset_class": profile.asset_class,
                "sector": ", ".join(item.label for item in profile.sector_exposure) or None,
                "geography": ", ".join(item.label for item in profile.geographic_exposure) or None,
                "average_volume": profile.average_volume,
                "price": metrics.current_price,
                "return_1d": metrics.return_1d,
                "return_1w": metrics.return_1w,
                "return_1m": metrics.return_1m,
                "return_3m": metrics.return_3m,
                "return_ytd": metrics.return_ytd,
                "return_1y": metrics.return_1y,
                "volatility": metrics.annualized_volatility,
                "drawdown": metrics.maximum_drawdown,
                "aum": profile.aum,
                "expense_ratio": profile.expense_ratio,
                "dividend_yield": profile.dividend_yield,
                "omni_score": omni.score,
                "source": profile.source,
                "updated_at": profile.updated_at,
            }
            rows.append(row)
            if not history.empty:
                analyses_for_signals.append(
                    {
                        "ticker": profile.ticker,
                        "name": profile.name,
                        "history": history,
                        "omni_score": omni.score,
                    }
                )
            payload = {
                "updated_at": _now(),
                "source": "live",
                "universe_name": ETF_UNIVERSE_NAME,
                "universe": tickers,
                "asset_type": AssetType.ETF,
                "rows": rows,
                "failures": failures,
                "partial": len(rows) < len(profiles),
                "note": "ETF OmniScore is a research composite and is not a validated forecast.",
            }
            save_named_scan_cache(ETF_SCREENER_CACHE_KEY, _json_safe_screener(payload))
        payload = {
            "updated_at": _now(),
            "source": "live",
            "universe_name": ETF_UNIVERSE_NAME,
            "universe": tickers,
            "asset_type": AssetType.ETF,
            "rows": rows,
            "failures": failures,
            "partial": False,
            "note": "ETF OmniScore is a research composite and is not a validated forecast.",
        }
        save_named_scan_cache(ETF_SCREENER_CACHE_KEY, _json_safe_screener(payload))
        if log_signals:
            for item in analyses_for_signals:
                log_etf_signals(
                    ticker=item["ticker"],
                    name=item["name"],
                    history=item["history"],
                    omni_score=item["omni_score"],
                    origin="etf_screener",
                )
        return self._filter_screener(payload, filters)

    def build_analysis(self, ticker: str, *, refresh: bool = False) -> dict[str, Any] | None:
        normalized = ticker.upper().strip()
        profile = self.get_profile(normalized, refresh=refresh)
        if profile is None or not _is_etf_profile(profile, normalized):
            return None
        history = fetch_price_history(normalized, period="5y")
        metrics = build_performance_metrics(history)
        holdings = self.get_holdings(normalized, refresh=refresh)
        flows = self._provider.get_flows(normalized)
        stock_scores = load_stock_signal_scores()
        underlying_score, coverage, contributors = thematic_exposure_score(
            holdings.holdings if holdings else (),
            stock_scores,
        )
        omni = build_etf_omni_score(
            profile,
            metrics,
            holdings,
            underlying_exposure_score=underlying_score,
            underlying_coverage_weight=coverage,
        )
        short_term_view = None
        short_term_recommendation = None
        if not history.empty:
            try:
                short_term_view = build_short_term_view(history)
                short_term_recommendation = build_short_term_recommendation(short_term_view)
            except Exception:
                short_term_view = None
                short_term_recommendation = None
        top_holdings = []
        if holdings is not None:
            top_holdings = [holding.to_dict() for holding in holdings.holdings[:10]]
        enriched = add_technical_indicators(history) if not history.empty else history
        return {
            "asset_type": AssetType.ETF,
            "ticker": normalized,
            "profile": profile.to_dict(),
            "metrics": metrics.to_dict(),
            "risk": {
                "annualized_volatility": metrics.annualized_volatility,
                "maximum_drawdown": metrics.maximum_drawdown,
                "sharpe_ratio": metrics.sharpe_ratio,
                "downside_volatility": metrics.downside_volatility,
                "insufficient_data": list(metrics.insufficient_data),
            },
            "holdings": holdings.to_dict() if holdings is not None else None,
            "top_holdings": top_holdings,
            "flows": flows.to_dict(),
            "omni_score": omni.to_dict(),
            "underlying_signal_exposure": {
                "exposure_score": underlying_score,
                "coverage_weight": coverage,
                "contributing_holdings": [item.to_dict() for item in contributors],
                "available": underlying_score is not None,
            },
            "short_term_view": asdict(short_term_view) if short_term_view is not None else None,
            "short_term_recommendation": asdict(short_term_recommendation) if short_term_recommendation is not None else None,
            "history": _history_records(history),
            "enriched_history": _history_records(enriched),
            "data_unavailable_label": DATA_UNAVAILABLE,
            "note": "Missing ETF fields are shown as unavailable rather than zero.",
        }

    def compare(self, tickers: Sequence[str]) -> dict[str, Any]:
        from domain.etf.models import EtfHolding

        normalized = list(dict.fromkeys(ticker.upper().strip() for ticker in tickers if ticker.strip()))
        if len(normalized) < 2:
            raise ValueError("Select two or more ETFs to compare.")
        analyses = []
        for ticker in normalized:
            analysis = self.build_analysis(ticker)
            if analysis is None:
                continue
            analyses.append(analysis)
        if len(analyses) < 2:
            raise ValueError("At least two valid ETFs are required for comparison.")

        def close_series(item: dict[str, Any]) -> pd.Series:
            records = item.get("history") or []
            if not records:
                return pd.Series(dtype=float)
            frame = pd.DataFrame(records)
            if "Date" not in frame.columns or "Close" not in frame.columns:
                return pd.Series(dtype=float)
            series = pd.to_numeric(frame["Close"], errors="coerce")
            series.index = pd.to_datetime(frame["Date"])
            return series.dropna()

        def holding_models(item: dict[str, Any]) -> list[EtfHolding]:
            return [
                EtfHolding(
                    etf_ticker=item["ticker"],
                    holding_ticker=row.get("holding_ticker"),
                    holding_name=row.get("holding_name"),
                    weight=row.get("weight"),
                )
                for row in ((item.get("holdings") or {}).get("holdings") or [])
            ]

        pairs = []
        for index, left in enumerate(analyses):
            for right in analyses[index + 1 :]:
                left_models = holding_models(left)
                right_models = holding_models(right)
                overlap = pairwise_overlap(left_models, right_models) if left_models and right_models else None
                shared, unique_a, unique_b = shared_and_unique(left_models, right_models)
                left_sector = (left.get("holdings") or {}).get("sector_allocation") or left["profile"].get("sector_exposure") or []
                right_sector = (right.get("holdings") or {}).get("sector_allocation") or right["profile"].get("sector_exposure") or []
                left_geo = (left.get("holdings") or {}).get("geographic_allocation") or left["profile"].get("geographic_exposure") or []
                right_geo = (right.get("holdings") or {}).get("geographic_allocation") or right["profile"].get("geographic_exposure") or []
                pairs.append(
                    {
                        "ticker_a": left["ticker"],
                        "ticker_b": right["ticker"],
                        "overlap": overlap,
                        "overlap_pct": None if overlap is None else overlap * 100.0,
                        "shared_holdings": [item.to_dict() for item in shared[:15]],
                        "unique_holdings_a": [item.to_dict() for item in unique_a[:10]],
                        "unique_holdings_b": [item.to_dict() for item in unique_b[:10]],
                        "sector_exposure": _allocation_from_dicts(left_sector, right_sector),
                        "geographic_exposure": _allocation_from_dicts(left_geo, right_geo),
                        "correlation": aligned_correlation(close_series(left), close_series(right)),
                        "top_10_concentration_a": (left.get("holdings") or {}).get("top_10_concentration"),
                        "top_10_concentration_b": (right.get("holdings") or {}).get("top_10_concentration"),
                    }
                )
        return {
            "etfs": [
                {
                    "ticker": item["ticker"],
                    "profile": profile_compare_row(
                        EtfProfile(
                            ticker=item["ticker"],
                            name=item["profile"].get("name"),
                            issuer=item["profile"].get("issuer"),
                            category=item["profile"].get("category"),
                            expense_ratio=item["profile"].get("expense_ratio"),
                            aum=item["profile"].get("aum"),
                            average_volume=item["profile"].get("average_volume"),
                            dividend_yield=item["profile"].get("dividend_yield"),
                        )
                    ),
                    "metrics": item["metrics"],
                    "omni_score": item["omni_score"],
                    "holdings_available": item["holdings"] is not None,
                }
                for item in analyses
            ],
            "pairs": pairs,
            "note": "Comparison presents overlapping holdings and risk metrics. It does not name a winner.",
        }

    def stock_exposure(self, stock_ticker: str) -> dict[str, Any]:
        holdings = self._repository.list_holdings_for_stock(stock_ticker)
        profiles = {profile.ticker: profile for profile in self._repository.list_profiles()}
        rows = reverse_etf_exposure(stock_ticker, holdings, profiles, min_weight=MIN_ETF_EXPOSURE_WEIGHT)
        return {
            "ticker": stock_ticker.upper().strip(),
            "available": bool(rows),
            "message": None if rows else "No cached ETF holdings currently include this stock.",
            "etfs": [row.to_dict() for row in rows],
        }

    def underlying_exposures(self) -> list[dict[str, Any]]:
        stock_scores = load_stock_signal_scores()
        if not stock_scores:
            return []
        results: list[UnderlyingSignalExposure] = []
        for ticker in DEFAULT_ETF_UNIVERSE:
            holdings = self._repository.get_holdings(ticker)
            if holdings is None:
                continue
            profile = self._repository.get_profile(ticker)
            score, coverage, contributors = thematic_exposure_score(holdings.holdings, stock_scores)
            if score is None:
                continue
            results.append(
                UnderlyingSignalExposure(
                    etf_ticker=ticker,
                    etf_name=profile.name if profile else None,
                    exposure_score=score,
                    contributing_holdings=contributors,
                    coverage_weight=coverage,
                )
            )
        results.sort(key=lambda item: item.exposure_score, reverse=True)
        return [item.to_dict() for item in results]

    def _filter_screener(self, payload: dict[str, Any], filters: EtfUniverseFilters | None) -> dict[str, Any]:
        rows = list(payload.get("rows") or [])
        if filters:
            rows = [row for row in rows if _row_matches(row, filters)]
        return {**payload, "rows": rows, "filtered_count": len(rows)}


def _row_matches(row: dict[str, Any], filters: EtfUniverseFilters) -> bool:
    def contains(value: Any, query: str | None) -> bool:
        if not query:
            return True
        return query.lower() in str(value or "").lower()

    if not contains(row.get("ticker"), filters.ticker):
        return False
    if not contains(row.get("name"), filters.name):
        return False
    if not contains(row.get("issuer"), filters.issuer):
        return False
    if not contains(row.get("asset_class"), filters.asset_class):
        return False
    if not contains(row.get("category"), filters.category):
        return False
    if not contains(row.get("sector"), filters.sector):
        return False
    if not contains(row.get("geography"), filters.geography):
        return False
    if filters.max_expense_ratio is not None:
        expense = row.get("expense_ratio")
        if expense is None or float(expense) > filters.max_expense_ratio:
            return False
    if filters.min_aum is not None:
        aum = row.get("aum")
        if aum is None or float(aum) < filters.min_aum:
            return False
    if filters.min_average_volume is not None:
        volume = row.get("average_volume") if "average_volume" in row else None
        if volume is None or float(volume) < filters.min_average_volume:
            return False
    if filters.min_dividend_yield is not None:
        dividend = row.get("dividend_yield")
        if dividend is None or float(dividend) < filters.min_dividend_yield:
            return False
    return True


def _json_safe_screener(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, default=str))


def _allocation_from_dicts(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from domain.etf.models import AllocationSlice

    def to_slices(items: list[dict[str, Any]]) -> tuple[AllocationSlice, ...]:
        slices: list[AllocationSlice] = []
        for item in items:
            label = str(item.get("label") or "")
            weight = item.get("weight")
            if not label or weight is None:
                continue
            slices.append(AllocationSlice(label=label, weight=float(weight), source=item.get("source")))
        return tuple(slices)

    return allocation_compare(to_slices(left), to_slices(right))


def load_stock_signal_scores() -> dict[str, float]:
    cached = load_named_scan_cache("global") or load_named_scan_cache("default")
    if not cached:
        return {}
    scores: dict[str, float] = {}
    for row in cached.get("short_term") or []:
        ticker = str(row.get("ticker") or "").upper().strip()
        score = row.get("short_term_score")
        if ticker and isinstance(score, (int, float)):
            scores[ticker] = float(score)
    return scores


__all__ = ["EtfService", "load_stock_signal_scores"]
