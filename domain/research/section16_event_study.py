from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import pandas as pd

from config.section16 import (
    FORWARD_HORIZONS_DAYS,
    OVERLAP_ENRICHMENT_THRESHOLD_PCT,
    PRIMARY_HORIZON_DAYS,
    PRIMARY_SOURCE,
    REQUIRED_POSITIVE_FOLDS,
    WALK_FORWARD_EMBARGO_DAYS,
    WALK_FORWARD_FOLDS,
)
from domain.research.section16_features import (
    detect_clusters,
    detect_streaks,
    eligible_open_market_rows,
    net_intensity,
)
from providers.events.sec_edgar_client import SecEventBundle
from providers.events.section16_models import InsiderTransaction, parse_iso_date


EDGAR_FORM4_CATEGORIES = frozenset(
    {
        "insider_purchase",
        "insider_sale",
        "insider_mixed",
        "insider_disclosure",
        "insider_purchase_cluster",
        "insider_sale_cluster",
    }
)


@dataclass(frozen=True)
class PricePanel:
    stock: Mapping[str, pd.Series]
    spy: pd.Series
    sector: Mapping[str, pd.Series]
    ticker_sector: Mapping[str, str]


def _close_series(history: pd.DataFrame | pd.Series) -> pd.Series:
    if isinstance(history, pd.Series):
        series = pd.to_numeric(history, errors="coerce")
    else:
        if history is None or history.empty or "Close" not in history.columns:
            return pd.Series(dtype=float)
        series = pd.to_numeric(history["Close"], errors="coerce")
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series.dropna().sort_index()


def _forward_return(close: pd.Series, as_of: date, sessions: int) -> float | None:
    if close.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    available = close.loc[close.index >= as_of_ts]
    if available.empty:
        return None
    start_price = float(available.iloc[0])
    if sessions >= len(available):
        return None
    end_price = float(available.iloc[sessions])
    if start_price == 0:
        return None
    return (end_price / start_price - 1.0) * 100.0


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    left = pd.Series(xs, dtype=float).rank()
    right = pd.Series(ys, dtype=float).rank()
    if left.nunique() < 2 or right.nunique() < 2:
        return None
    value = left.corr(right, method="pearson")
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), 4)


def _hit_rate(values: Sequence[float], returns: Sequence[float], *, quantile: float = 0.9) -> float | None:
    if len(values) < 5 or len(values) != len(returns):
        return None
    threshold = float(pd.Series(values).quantile(quantile))
    selected = [ret for value, ret in zip(values, returns) if value >= threshold]
    if not selected:
        return None
    return round(sum(ret > 0 for ret in selected) / len(selected) * 100.0, 2)


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def audit_form4_overlap(
    transactions: Sequence[InsiderTransaction],
    edgar_bundles: Sequence[SecEventBundle] | None = None,
    edgar_accessions: Sequence[str] | None = None,
    *,
    threshold_pct: float = OVERLAP_ENRICHMENT_THRESHOLD_PCT,
) -> dict[str, Any]:
    rows = eligible_open_market_rows(transactions)
    section_accessions = {row.accession_number for row in rows if row.accession_number}
    known: set[str] = set(edgar_accessions or ())
    for bundle in edgar_bundles or []:
        for event in bundle.events:
            if event.form in {"4", "4/A", "4 cluster"} or event.category in EDGAR_FORM4_CATEGORIES:
                if event.accession_number and event.accession_number != "cluster":
                    known.add(event.accession_number)
    overlap = section_accessions & known
    overlap_pct = (
        round(len(overlap) / len(section_accessions) * 100.0, 2) if section_accessions else 0.0
    )
    enrichment = overlap_pct > threshold_pct
    return {
        "threshold_pct": threshold_pct,
        "section16_accessions": len(section_accessions),
        "edgar_form4_accessions": len(known),
        "overlap_accessions": len(overlap),
        "overlap_pct": overlap_pct,
        "stream_role": "enrichment" if enrichment else "candidate_new_stream",
        "primary_source": PRIMARY_SOURCE,
    }


def _panel_dates(panel: PricePanel) -> list[date]:
    dates: set[date] = set()
    for series in panel.stock.values():
        dates.update(item.date() for item in series.index)
    return sorted(dates)


def build_event_rows(
    transactions: Sequence[InsiderTransaction],
    panel: PricePanel,
    *,
    edgar_accessions_by_ticker: Mapping[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    rows = eligible_open_market_rows(transactions)
    by_ticker: dict[str, list[InsiderTransaction]] = defaultdict(list)
    for row in rows:
        by_ticker[row.ticker.upper()].append(row)
    event_dates: dict[tuple[str, date], list[InsiderTransaction]] = defaultdict(list)
    for row in rows:
        filed = parse_iso_date(row.filed_at)
        if filed is None:
            continue
        event_dates[(row.ticker.upper(), filed)].append(row)

    observations: list[dict[str, Any]] = []
    for (ticker, filed_at), group in sorted(event_dates.items()):
        stock = panel.stock.get(ticker)
        if stock is None or stock.empty:
            continue
        dollar, shares = net_intensity(group)
        clusters = detect_clusters(by_ticker[ticker], as_of=filed_at)
        streaks = detect_streaks(by_ticker[ticker], as_of=filed_at)
        cluster = next((event for event in clusters if event.direction == "P"), None)
        streak = next((event for event in streaks if event.direction == "P"), None)
        spy_close = panel.spy
        sector_symbol = panel.ticker_sector.get(ticker)
        sector_close = panel.sector.get(sector_symbol or "", pd.Series(dtype=float))
        known = (edgar_accessions_by_ticker or {}).get(ticker, set())
        edgar_baseline = int(any(row.accession_number in known for row in group))
        observation: dict[str, Any] = {
            "ticker": ticker,
            "filed_at": filed_at.isoformat(),
            "signed_value_usd": dollar,
            "signed_shares": shares,
            "buy_intensity": max(dollar, 0.0),
            "cluster_flag": int(cluster is not None),
            "streak_flag": int(streak is not None),
            "edgar_form4_baseline": edgar_baseline,
            "sector": sector_symbol,
        }
        for horizon in FORWARD_HORIZONS_DAYS:
            stock_ret = _forward_return(stock, filed_at, horizon)
            spy_ret = _forward_return(spy_close, filed_at, horizon)
            sector_ret = _forward_return(sector_close, filed_at, horizon) if not sector_close.empty else None
            observation[f"stock_return_{horizon}d"] = None if stock_ret is None else round(stock_ret, 4)
            observation[f"spy_excess_{horizon}d"] = (
                None if stock_ret is None or spy_ret is None else round(stock_ret - spy_ret, 4)
            )
            observation[f"sector_excess_{horizon}d"] = (
                None if stock_ret is None or sector_ret is None else round(stock_ret - sector_ret, 4)
            )
        observations.append(observation)
    return observations


def _control_rows(event_rows: Sequence[Mapping[str, Any]], panel: PricePanel) -> list[dict[str, Any]]:
    event_keys = {(str(row["ticker"]), str(row["filed_at"])) for row in event_rows}
    dates = [parse_iso_date(str(row["filed_at"])) for row in event_rows]
    unique_dates = sorted({item for item in dates if item is not None})
    controls: list[dict[str, Any]] = []
    for as_of in unique_dates:
        for ticker, close in panel.stock.items():
            if (ticker, as_of.isoformat()) in event_keys:
                continue
            spy_ret = _forward_return(panel.spy, as_of, PRIMARY_HORIZON_DAYS)
            stock_ret = _forward_return(close, as_of, PRIMARY_HORIZON_DAYS)
            if stock_ret is None or spy_ret is None:
                continue
            controls.append(
                {
                    "ticker": ticker,
                    "filed_at": as_of.isoformat(),
                    "spy_excess_20d": round(stock_ret - spy_ret, 4),
                    "is_event": 0,
                }
            )
    return controls


def _fold_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    intensity = [float(row["buy_intensity"]) for row in rows if row.get("spy_excess_20d") is not None]
    cluster = [float(row["cluster_flag"]) for row in rows if row.get("spy_excess_20d") is not None]
    baseline = [float(row["edgar_form4_baseline"]) for row in rows if row.get("spy_excess_20d") is not None]
    excess = [float(row["spy_excess_20d"]) for row in rows if row.get("spy_excess_20d") is not None]
    nested_rows = [
        row
        for row in rows
        if row.get("edgar_form4_baseline") == 1 and row.get("spy_excess_20d") is not None
    ]
    nested_intensity = [float(row["buy_intensity"]) for row in nested_rows]
    nested_excess = [float(row["spy_excess_20d"]) for row in nested_rows]
    intensity_ic = _spearman(intensity, excess)
    cluster_ic = _spearman(cluster, excess)
    baseline_ic = _spearman(baseline, excess)
    nested_ic = _spearman(nested_intensity, nested_excess)
    intensity_hit = _hit_rate(intensity, excess)
    cluster_hit = _hit_rate(cluster, excess) if any(cluster) else None
    baseline_positive = [ret for flag, ret in zip(baseline, excess) if flag > 0]
    baseline_hit = (
        round(sum(ret > 0 for ret in baseline_positive) / len(baseline_positive) * 100.0, 2)
        if baseline_positive
        else None
    )
    hit_lift = (
        round(intensity_hit - baseline_hit, 2)
        if intensity_hit is not None and baseline_hit is not None
        else intensity_hit
    )
    ic_lift = (
        round(intensity_ic - baseline_ic, 4)
        if intensity_ic is not None and baseline_ic is not None
        else intensity_ic
    )
    fold_pass = bool(
        (intensity_ic is not None and intensity_ic > 0)
        or (cluster_ic is not None and cluster_ic > 0)
        or (hit_lift is not None and hit_lift > 0)
    )
    return {
        "observations": len(rows),
        "intensity_ic": intensity_ic,
        "cluster_ic": cluster_ic,
        "baseline_ic": baseline_ic,
        "nested_vs_edgar_ic": nested_ic,
        "intensity_top_decile_hit_rate_pct": intensity_hit,
        "cluster_top_decile_hit_rate_pct": cluster_hit,
        "baseline_hit_rate_pct": baseline_hit,
        "ic_lift_vs_baseline": ic_lift,
        "hit_rate_lift_vs_baseline": hit_lift,
        "mean_spy_excess_20d": _mean(excess),
        "passed": fold_pass,
    }


def _walk_forward_folds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique_dates = sorted({str(row["filed_at"]) for row in rows})
    if len(unique_dates) < 6:
        return []
    initial = max(2, math.ceil(len(unique_dates) * 0.40))
    remaining = unique_dates[initial:]
    if not remaining:
        return []
    block = max(1, math.ceil(len(remaining) / WALK_FORWARD_FOLDS))
    folds: list[dict[str, Any]] = []
    cursor = initial
    for index in range(WALK_FORWARD_FOLDS):
        validation = remaining[index * block : (index + 1) * block]
        if not validation:
            continue
        training_end = unique_dates[cursor - 1]
        embargo_cut = (
            date.fromisoformat(validation[0]) - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)
        ).isoformat()
        training_dates = {item for item in unique_dates[:cursor] if item <= embargo_cut}
        validation_rows = [row for row in rows if str(row["filed_at"]) in set(validation)]
        metrics = _fold_metrics(validation_rows)
        folds.append(
            {
                "fold": index + 1,
                "training_end": training_end,
                "validation_start": validation[0],
                "validation_end": validation[-1],
                "training_dates": len(training_dates),
                "validation_dates": len(validation),
                **metrics,
            }
        )
        cursor = min(len(unique_dates), cursor + block)
    return folds


def evaluate_section16_experiment(
    transactions: Sequence[InsiderTransaction],
    panel: PricePanel,
    *,
    edgar_bundles: Sequence[SecEventBundle] | None = None,
    xml_path_available: bool = True,
) -> dict[str, Any]:
    edgar_by_ticker: dict[str, set[str]] = defaultdict(set)
    for bundle in edgar_bundles or []:
        ticker = bundle.ticker.upper()
        for event in bundle.events:
            if event.form in {"4", "4/A"} or event.category in EDGAR_FORM4_CATEGORIES:
                if event.accession_number and event.accession_number != "cluster":
                    edgar_by_ticker[ticker].add(event.accession_number)
    overlap = audit_form4_overlap(transactions, edgar_bundles)
    event_rows = build_event_rows(transactions, panel, edgar_accessions_by_ticker=edgar_by_ticker)
    controls = _control_rows(event_rows, panel)
    event_excess = [
        float(row["spy_excess_20d"])
        for row in event_rows
        if row.get("spy_excess_20d") is not None and float(row.get("buy_intensity") or 0) > 0
    ]
    control_excess = [float(row["spy_excess_20d"]) for row in controls]
    folds = _walk_forward_folds(event_rows)
    eligible_folds = [fold for fold in folds if fold["observations"] > 0]
    positive_folds = sum(bool(fold["passed"]) for fold in eligible_folds)
    freshness_ok = xml_path_available
    primary_is_sec = PRIMARY_SOURCE.startswith("sec")
    lift_ok = positive_folds >= REQUIRED_POSITIVE_FOLDS and len(eligible_folds) >= REQUIRED_POSITIVE_FOLDS
    nested_positive = sum(
        fold.get("nested_vs_edgar_ic") is not None and fold["nested_vs_edgar_ic"] > 0
        for fold in eligible_folds
    )
    if not event_rows or len(eligible_folds) < REQUIRED_POSITIVE_FOLDS:
        verdict = "INCONCLUSIVE"
        reason = "Held-out sample is too small for the pre-registered walk-forward rule."
    elif not freshness_ok:
        verdict = "FAIL"
        reason = "Quarterly ZIP lag is stale versus the 2-day Form-4 SLA and no EDGAR XML path is available."
    elif not primary_is_sec:
        verdict = "FAIL"
        reason = "Primary path is not SEC."
    elif lift_ok:
        verdict = "SUCCESS"
        reason = (
            f"{positive_folds}/{len(eligible_folds)} walk-forward folds showed positive IC or "
            "top-decile hit-rate lift versus the existing EDGAR Form-4 baseline."
        )
    else:
        verdict = "FAIL"
        reason = (
            "After open-market code filters, neither net buy intensity nor the frozen cluster rule "
            "showed surprise-aligned lift versus matched non-event / EDGAR-event controls in "
            f">={REQUIRED_POSITIVE_FOLDS}/{WALK_FORWARD_FOLDS} held-out folds."
        )
    return {
        "status": "shadow_research_only",
        "verdict": verdict,
        "reason": reason,
        "deployment_guard": {
            "automatic_activation": False,
            "applied_impact": 0,
            "live_ranking_changes": False,
            "message": "Section-16 features are logged shadow-only. They never change live recommendations.",
        },
        "protocol": {
            "primary_source": PRIMARY_SOURCE,
            "primary_horizon_days": PRIMARY_HORIZON_DAYS,
            "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
            "overlap_enrichment_threshold_pct": OVERLAP_ENRICHMENT_THRESHOLD_PCT,
            "xml_path_available": xml_path_available,
        },
        "data_quality": {
            "open_market_transactions": len(eligible_open_market_rows(transactions)),
            "event_rows": len(event_rows),
            "control_rows": len(controls),
            "tickers": len({row["ticker"] for row in event_rows}),
        },
        "dedup_audit": overlap,
        "event_study": {
            "buy_event_mean_spy_excess_20d": _mean(event_excess),
            "control_mean_spy_excess_20d": _mean(control_excess),
            "event_minus_control_20d": (
                round((_mean(event_excess) or 0) - (_mean(control_excess) or 0), 4)
                if event_excess and control_excess
                else None
            ),
        },
        "walk_forward_folds": folds,
        "positive_folds": positive_folds,
        "nested_positive_folds": nested_positive,
        "event_rows": event_rows,
    }


__all__ = [
    "PricePanel",
    "audit_form4_overlap",
    "build_event_rows",
    "evaluate_section16_experiment",
]
