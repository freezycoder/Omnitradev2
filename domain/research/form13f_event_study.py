from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import pandas as pd

from config.form13f import (
    FORWARD_HORIZONS_DAYS,
    MATCH_MAX_LOG_ADV_DISTANCE,
    MIN_FOLD_EVENTS,
    PRIMARY_HORIZON_DAYS,
    PRIMARY_SOURCE,
    REQUIRED_POSITIVE_FOLDS,
    WALK_FORWARD_EMBARGO_DAYS,
    WALK_FORWARD_FOLDS,
)
from domain.research.form13f_features import (
    detect_clusters,
    detect_streaks,
    event_date_is_lag_correct,
    primary_cluster_events,
    single_holder_entries,
)
from providers.events.form13f_models import HoldingPosition, parse_iso_date


class PricePanel:
    def __init__(
        self,
        stock: Mapping[str, pd.Series],
        spy: pd.Series,
        volume: Mapping[str, pd.Series] | None = None,
    ) -> None:
        self.stock = {ticker.upper(): series for ticker, series in stock.items()}
        self.spy = spy
        self.volume = {ticker.upper(): series for ticker, series in (volume or {}).items()}


def _close_series(history: pd.DataFrame | pd.Series) -> pd.Series:
    if isinstance(history, pd.Series):
        series = pd.to_numeric(history, errors="coerce")
    else:
        if history is None or history.empty or "Close" not in history.columns:
            return pd.Series(dtype=float)
        series = pd.to_numeric(history["Close"], errors="coerce")
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series.dropna().sort_index()


def _volume_series(history: pd.DataFrame | pd.Series) -> pd.Series:
    if isinstance(history, pd.Series):
        series = pd.to_numeric(history, errors="coerce")
    else:
        if history is None or history.empty or "Volume" not in history.columns:
            return pd.Series(dtype=float)
        series = pd.to_numeric(history["Volume"], errors="coerce")
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series.dropna().sort_index()


def _forward_return(close: pd.Series, as_of: date, sessions: int) -> float | None:
    if close.empty:
        return None
    available = close.loc[close.index >= pd.Timestamp(as_of)]
    if available.empty or sessions >= len(available):
        return None
    start_price = float(available.iloc[0])
    end_price = float(available.iloc[sessions])
    if start_price == 0:
        return None
    return (end_price / start_price - 1.0) * 100.0


def _trailing_adv_usd(close: pd.Series, volume: pd.Series, as_of: date, sessions: int = 20) -> float | None:
    if close.empty:
        return None
    as_of_ts = pd.Timestamp(as_of)
    history = close.loc[close.index < as_of_ts].tail(sessions)
    if history.empty:
        return None
    if volume.empty:
        return float(history.mean())
    vol = volume.reindex(history.index).fillna(0.0)
    dollar = history * vol
    if dollar.empty:
        return None
    return float(dollar.mean())


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _tstat(values: Sequence[float]) -> float | None:
    if len(values) < 3:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    if variance <= 0:
        return None
    return round(mean / math.sqrt(variance / len(values)), 4)


def _log_or_none(value: float | None) -> float | None:
    if value is None or value <= 0:
        return None
    return math.log(value)


def _horizon_fields(stock: pd.Series, spy: pd.Series, as_of: date) -> dict[str, float | None]:
    fields: dict[str, float | None] = {}
    for horizon in FORWARD_HORIZONS_DAYS:
        stock_ret = _forward_return(stock, as_of, horizon)
        spy_ret = _forward_return(spy, as_of, horizon)
        fields[f"stock_return_{horizon}d"] = None if stock_ret is None else round(stock_ret, 4)
        fields[f"spy_excess_{horizon}d"] = (
            None if stock_ret is None or spy_ret is None else round(stock_ret - spy_ret, 4)
        )
    return fields


def _characteristics(panel: PricePanel, ticker: str, as_of: date) -> dict[str, float | None]:
    close = panel.stock.get(ticker.upper(), pd.Series(dtype=float))
    volume = panel.volume.get(ticker.upper(), pd.Series(dtype=float))
    available = close.loc[close.index >= pd.Timestamp(as_of)]
    price = float(available.iloc[0]) if not available.empty else None
    adv = _trailing_adv_usd(close, volume, as_of)
    return {"price": price, "adv_usd": adv, "log_adv": _log_or_none(adv)}


def _match_control(
    event_chars: Mapping[str, float | None],
    candidates: Sequence[tuple[str, dict[str, float | None]]],
) -> tuple[str, float] | None:
    event_log_adv = event_chars.get("log_adv")
    if event_log_adv is None:
        return None
    best: tuple[str, float] | None = None
    for ticker, chars in candidates:
        cand_log = chars.get("log_adv")
        if cand_log is None:
            continue
        distance = abs(float(event_log_adv) - float(cand_log))
        if distance > MATCH_MAX_LOG_ADV_DISTANCE:
            continue
        if best is None or distance < best[1]:
            best = (ticker, distance)
    return best


def build_event_rows(
    holdings: Sequence[HoldingPosition],
    panel: PricePanel,
    *,
    form4_cluster_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    clusters = detect_clusters(holdings)
    streaks = detect_streaks(holdings)
    single_holders = single_holder_entries(holdings)
    cluster_keys = {(event.ticker, event.reportable_quarter) for event in clusters}
    observations: list[dict[str, Any]] = []

    def _append(
        *,
        ticker: str,
        event_date: str,
        reportable_quarter: str,
        family: str,
        direction: str,
        etf_churn_suspect: bool,
        notable_count: int,
    ) -> None:
        close = panel.stock.get(ticker.upper())
        filed = parse_iso_date(event_date)
        period_end = parse_iso_date(reportable_quarter)
        if close is None or close.empty or filed is None:
            return
        chars = _characteristics(panel, ticker, filed)
        form4_hit = 0
        if form4_cluster_keys:
            form4_hit = int((ticker.upper(), event_date) in form4_cluster_keys)
        row: dict[str, Any] = {
            "ticker": ticker.upper(),
            "family": family,
            "direction": direction,
            "reportable_quarter": reportable_quarter,
            "event_date": event_date,
            "lag_correct": event_date_is_lag_correct(event_date, reportable_quarter),
            "quarter_end": None if period_end is None else period_end.isoformat(),
            "filing_lag_days": None if period_end is None else (filed - period_end).days,
            "etf_churn_suspect": int(etf_churn_suspect),
            "notable_count": notable_count,
            "form4_cluster": form4_hit,
            "primary_book": int(family == "cluster_entry" and not etf_churn_suspect),
            **chars,
            **_horizon_fields(close, panel.spy, filed),
        }
        observations.append(row)

    for event in clusters:
        _append(
            ticker=event.ticker,
            event_date=event.event_date,
            reportable_quarter=event.reportable_quarter,
            family=f"cluster_{event.direction}",
            direction=event.direction,
            etf_churn_suspect=event.etf_churn_suspect,
            notable_count=event.notable_count,
        )
    for event in streaks:
        _append(
            ticker=event.ticker,
            event_date=event.event_date,
            reportable_quarter=event.reportable_quarter,
            family="streak",
            direction="entry",
            etf_churn_suspect=False,
            notable_count=event.net_notable_adds,
        )
    for ticker, quarter, filed_at in single_holders:
        if (ticker, quarter) in cluster_keys:
            continue
        _append(
            ticker=ticker,
            event_date=filed_at,
            reportable_quarter=quarter,
            family="single_holder_entry",
            direction="entry",
            etf_churn_suspect=False,
            notable_count=1,
        )
    _attach_matches(observations, panel, cluster_keys)
    observations.sort(key=lambda row: (str(row["event_date"]), str(row["ticker"]), str(row["family"])))
    return observations


def _attach_matches(
    observations: list[dict[str, Any]],
    panel: PricePanel,
    cluster_keys: set[tuple[str, str]],
) -> None:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        by_date[str(row["event_date"])].append(row)
    for event_date, rows in by_date.items():
        filed = parse_iso_date(event_date)
        if filed is None:
            continue
        occupied = {str(row["ticker"]) for row in rows if row["family"].startswith("cluster_")}
        candidates: list[tuple[str, dict[str, float | None]]] = []
        for ticker in panel.stock:
            if ticker in occupied:
                continue
            if any((ticker, str(row["reportable_quarter"])) in cluster_keys for row in rows):
                continue
            candidates.append((ticker, _characteristics(panel, ticker, filed)))
        for row in rows:
            match = _match_control(
                {"log_adv": row.get("log_adv")},
                candidates,
            )
            if match is None:
                row["matched_ticker"] = None
                row["match_log_adv_distance"] = None
                for horizon in FORWARD_HORIZONS_DAYS:
                    row[f"matched_excess_{horizon}d"] = None
                continue
            matched_ticker, distance = match
            matched_close = panel.stock[matched_ticker]
            row["matched_ticker"] = matched_ticker
            row["match_log_adv_distance"] = round(distance, 4)
            for horizon in FORWARD_HORIZONS_DAYS:
                event_ret = _forward_return(panel.stock[str(row["ticker"])], filed, horizon)
                control_ret = _forward_return(matched_close, filed, horizon)
                row[f"matched_excess_{horizon}d"] = (
                    None if event_ret is None or control_ret is None else round(event_ret - control_ret, 4)
                )


def _fold_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary = [
        row
        for row in rows
        if row.get("primary_book") == 1 and row.get(f"matched_excess_{PRIMARY_HORIZON_DAYS}d") is not None
    ]
    spy_values = [float(row[f"spy_excess_{PRIMARY_HORIZON_DAYS}d"]) for row in primary if row.get(f"spy_excess_{PRIMARY_HORIZON_DAYS}d") is not None]
    matched_values = [float(row[f"matched_excess_{PRIMARY_HORIZON_DAYS}d"]) for row in primary]
    lag_ok = all(bool(row.get("lag_correct")) for row in primary) if primary else False
    matched_mean = _mean(matched_values)
    spy_mean = _mean(spy_values)
    subsumed = bool(
        spy_mean is not None and spy_mean > 0 and (matched_mean is None or matched_mean <= 0)
    )
    coverage_ok = len(primary) >= MIN_FOLD_EVENTS
    passed = bool(coverage_ok and matched_mean is not None and matched_mean > 0 and lag_ok)
    horizon_means = {
        f"matched_excess_{horizon}d": _mean(
            [
                float(row[f"matched_excess_{horizon}d"])
                for row in primary
                if row.get(f"matched_excess_{horizon}d") is not None
            ]
        )
        for horizon in FORWARD_HORIZONS_DAYS
    }
    return {
        "observations": len(rows),
        "primary_events": len(primary),
        "coverage_ok": coverage_ok,
        "lag_correct": lag_ok,
        "mean_spy_excess_20d": spy_mean,
        "mean_matched_excess_20d": matched_mean,
        "matched_tstat_20d": _tstat(matched_values),
        "size_liquidity_subsumed": subsumed,
        "passed": passed,
        **horizon_means,
    }


def _walk_forward_folds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique_dates = sorted({str(row["event_date"]) for row in rows if row.get("primary_book") == 1})
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
        validation_rows = [row for row in rows if str(row["event_date"]) in set(validation)]
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


def evaluate_form13f_experiment(
    holdings: Sequence[HoldingPosition],
    panel: PricePanel,
    *,
    form4_cluster_keys: set[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    event_rows = build_event_rows(holdings, panel, form4_cluster_keys=form4_cluster_keys)
    clusters = detect_clusters(holdings)
    primary = primary_cluster_events(clusters)
    primary_rows = [row for row in event_rows if row.get("primary_book") == 1]
    single_rows = [row for row in event_rows if row.get("family") == "single_holder_entry"]
    churn_rows = [row for row in event_rows if row.get("family") == "cluster_entry" and row.get("etf_churn_suspect") == 1]
    streak_rows = [row for row in event_rows if row.get("family") == "streak"]
    folds = _walk_forward_folds(event_rows)
    eligible_folds = [fold for fold in folds if fold["coverage_ok"]]
    positive_folds = sum(bool(fold["passed"]) for fold in eligible_folds)
    subsumed_folds = sum(bool(fold["size_liquidity_subsumed"]) for fold in eligible_folds)
    lag_ok = all(bool(row.get("lag_correct")) for row in primary_rows) if primary_rows else False
    nested_rows = [row for row in primary_rows if row.get("form4_cluster") == 0]
    coverage_ok = len(eligible_folds) >= REQUIRED_POSITIVE_FOLDS and len(primary_rows) >= MIN_FOLD_EVENTS
    etf_explains = bool(churn_rows) and not primary_rows
    lift_ok = positive_folds >= REQUIRED_POSITIVE_FOLDS and coverage_ok and lag_ok
    if not primary_rows or not coverage_ok:
        verdict = "INCONCLUSIVE"
        reason = "Held-out sample is too small for the pre-registered walk-forward coverage rule."
    elif not lag_ok:
        verdict = "FAIL"
        reason = "Event dates are not filing-availability dated; quarter-end look-ahead is forbidden."
    elif etf_explains:
        verdict = "FAIL"
        reason = "ETF/index churn filter removes the cluster-entry book."
    elif subsumed_folds >= REQUIRED_POSITIVE_FOLDS and positive_folds < REQUIRED_POSITIVE_FOLDS:
        verdict = "FAIL"
        reason = "Any remaining SPY-excess is subsumed by size/liquidity matching."
    elif lift_ok:
        verdict = "SUCCESS"
        reason = (
            f"{positive_folds}/{len(eligible_folds)} walk-forward folds showed positive "
            f"size/liquidity-matched {PRIMARY_HORIZON_DAYS}d excess for K=3 cluster-entry."
        )
    else:
        verdict = "FAIL"
        reason = (
            "After freezing taxonomy v1, K=3, filing-date lag, and ETF churn filters, "
            "cluster-entry (or streak) earned no matched excess versus non-cluster names "
            f"in >={REQUIRED_POSITIVE_FOLDS}/{WALK_FORWARD_FOLDS} held-out folds."
        )
    return {
        "status": "shadow_research_only",
        "verdict": verdict,
        "reason": reason,
        "deployment_guard": {
            "automatic_activation": False,
            "applied_impact": 0,
            "live_ranking_changes": False,
            "message": "13F cluster features are logged shadow-only. They never change live recommendations.",
        },
        "protocol": {
            "primary_source": PRIMARY_SOURCE,
            "taxonomy_version": "v1",
            "cluster_k": 3,
            "primary_horizon_days": PRIMARY_HORIZON_DAYS,
            "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
            "event_date_rule": "kth_notable_manager_filing_date",
        },
        "data_quality": {
            "holdings": len(holdings),
            "mapped_tickers": len({row.ticker for row in holdings if row.ticker}),
            "cluster_events": len(clusters),
            "primary_cluster_entries": len(primary),
            "event_rows": len(event_rows),
            "unmapped_cusips": len({row.cusip for row in holdings if not row.ticker}),
        },
        "event_study": {
            "cluster_entry_mean_matched_excess_20d": _mean(
                [
                    float(row[f"matched_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in primary_rows
                    if row.get(f"matched_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
            "cluster_entry_mean_spy_excess_20d": _mean(
                [
                    float(row[f"spy_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in primary_rows
                    if row.get(f"spy_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
            "single_holder_mean_matched_excess_20d": _mean(
                [
                    float(row[f"matched_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in single_rows
                    if row.get(f"matched_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
            "etf_churn_mean_spy_excess_20d": _mean(
                [
                    float(row[f"spy_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in churn_rows
                    if row.get(f"spy_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
            "streak_mean_matched_excess_20d": _mean(
                [
                    float(row[f"matched_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in streak_rows
                    if row.get(f"matched_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
            "orthogonal_to_form4_mean_matched_excess_20d": _mean(
                [
                    float(row[f"matched_excess_{PRIMARY_HORIZON_DAYS}d"])
                    for row in nested_rows
                    if row.get(f"matched_excess_{PRIMARY_HORIZON_DAYS}d") is not None
                ]
            ),
        },
        "etf_churn": {
            "suspect_cluster_entries": len(churn_rows),
            "primary_book_after_filter": len(primary_rows),
            "residual_risk": (
                "Closet indexers and unlisted reconstitution calendars can still remain "
                "inside the notable AUM-floor set. Q2 Russell and S&P reconstitution "
                "windows are labeled on events but only drop names when >=2 frozen "
                "passive/index 13F filers also enter or exit."
            ),
        },
        "walk_forward_folds": folds,
        "positive_folds": positive_folds,
        "eligible_folds": len(eligible_folds),
        "event_rows": event_rows,
    }


__all__ = [
    "PricePanel",
    "build_event_rows",
    "evaluate_form13f_experiment",
]
