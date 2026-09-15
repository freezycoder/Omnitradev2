from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from application.calibration_research_service import WALK_FORWARD_EMBARGO_DAYS, WALK_FORWARD_FOLDS
from config.industry_groups import (
    INDUSTRY_GROUP_MAP,
    INDUSTRY_GROUP_MAP_VERSION,
    MIN_LIQUID_UNIVERSE_COVERAGE,
    IndustryGroupMembership,
    industry_group_for_ticker,
    universe_coverage,
)
from domain.scoring.industry_group_rs import (
    MIN_HISTORY_SESSIONS_RECOMMENDED,
    RANK_LOOKBACK_SESSIONS,
    assign_industry_group_relative_strength,
    compute_group_avg_rs_frame,
    compute_group_rank_frame,
    compute_name_feature_frames,
    compute_rrg_frame,
    rrg_recipe_manifest,
)


PRIMARY_HORIZON_DAYS = 20
SECONDARY_HORIZONS_DAYS = (5, 60)
PRIMARY_METRICS = ("spearman_ic", "top_decile_hit_rate")
SAMPLE_ANCHOR = "W-FRI"
MIN_FEATURE_COVERAGE = 0.50
MIN_CROSS_SECTION = 8
MIN_FOLD_DATES = 4
MIN_FOLD_OBSERVATIONS = 20
BASELINE_FEATURES = (
    "raw_strength_pct",
    "universe_percentile",
    "sector_percentile",
    "market_relative_pct",
    "sector_relative_pct",
)
GROUP_FEATURES = (
    "group_avg_rs_pct",
    "group_rank",
    "group_rank_percentile",
    "rank_delta_1w",
    "rank_delta_1m",
    "rank_delta_3m",
    "rank_delta_6m",
    "rs_ratio",
    "rs_momentum",
)


@dataclass(frozen=True)
class NestedModelObservation:
    as_of: date
    ticker: str
    raw_strength_pct: float | None
    universe_percentile: float | None
    sector_percentile: float | None
    market_relative_pct: float | None
    sector_relative_pct: float | None
    group_id: str | None
    group_avg_rs_pct: float | None
    group_rank: float | None
    group_rank_percentile: float | None
    rank_delta_1w: float | None
    rank_delta_1m: float | None
    rank_delta_3m: float | None
    rank_delta_6m: float | None
    rs_ratio: float | None
    rs_momentum: float | None
    excess_5d: float | None
    excess_20d: float | None
    excess_60d: float | None
    singleton_group: bool = False

    def feature_value(self, name: str) -> float | None:
        value = getattr(self, name)
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number):
            return None
        return number


@dataclass(frozen=True)
class WalkForwardFoldSpec:
    fold: int
    training_end: date
    validation_start: date
    validation_end: date
    validation_dates: tuple[date, ...]
    eligible: bool
    ineligible_reason: str | None = None


@dataclass(frozen=True)
class NestedModelFoldResult:
    fold: int
    horizon_days: int
    eligible: bool
    n_train: int
    n_validation: int
    baseline: dict[str, float | None]
    nested: dict[str, float | None]
    lift: dict[str, float | None]
    used_baseline_features: tuple[str, ...]
    used_group_features: tuple[str, ...]
    abort_reason: str | None = None


class IndustryGroupRsEvalService:
    """Offline nested-model harness. Never writes live ranking or recommendations."""

    def __init__(
        self,
        *,
        mapping: Mapping[str, IndustryGroupMembership] | None = None,
        folds: int = WALK_FORWARD_FOLDS,
        embargo_days: int = WALK_FORWARD_EMBARGO_DAYS,
    ) -> None:
        self._mapping = mapping if mapping is not None else INDUSTRY_GROUP_MAP
        self._folds = max(int(folds), 1)
        self._embargo_days = max(int(embargo_days), 0)

    def evaluate_observations(
        self,
        observations: Sequence[NestedModelObservation],
        *,
        universe: Sequence[str] | None = None,
        history_sessions_max: int | None = None,
    ) -> dict[str, Any]:
        coverage = universe_coverage(universe, mapping=self._mapping)
        if universe is None:
            coverage = universe_coverage(
                sorted({row.ticker for row in observations}),
                mapping=self._mapping,
            )
        abort_reasons = self._abort_reasons(
            observations,
            coverage=coverage,
            history_sessions_max=history_sessions_max,
        )
        folds = self._build_folds(observations)
        fold_results = [
            self._evaluate_fold(observations, fold, horizon_days=PRIMARY_HORIZON_DAYS)
            for fold in folds
        ]
        secondary = {
            str(horizon): [
                self._evaluate_fold(observations, fold, horizon_days=horizon)
                for fold in folds
            ]
            for horizon in SECONDARY_HORIZONS_DAYS
        }
        verdict = self._verdict(fold_results, abort_reasons)
        return {
            "status": "research_only",
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_ranking_changes": False,
                "message": (
                    "Industry-group RS / RRG remains shadow-only. "
                    "This harness never writes production scores or ranking surfaces."
                ),
            },
            "pre_registration": {
                "primary_horizon_days": PRIMARY_HORIZON_DAYS,
                "primary_metrics": list(PRIMARY_METRICS),
                "secondary_horizons_days": list(SECONDARY_HORIZONS_DAYS),
                "rrg_recipe": rrg_recipe_manifest(),
                "map_version": INDUSTRY_GROUP_MAP_VERSION,
                "success_rule": (
                    "Nested model beats baseline on at least one primary 20d metric "
                    "with positive lift in at least 2 of 3 walk-forward folds."
                ),
                "includes_singleton_groups": True,
            },
            "coverage": coverage,
            "data_quality": self._data_quality(observations, history_sessions_max),
            "abort_reasons": abort_reasons,
            "walk_forward_folds": [asdict(fold) for fold in folds],
            "primary_horizon_results": [asdict(row) for row in fold_results],
            "secondary_horizon_results": {
                horizon: [asdict(row) for row in rows] for horizon, rows in secondary.items()
            },
            "verdict": verdict,
        }

    def evaluate_price_panel(
        self,
        *,
        stock_histories: Mapping[str, pd.DataFrame],
        market_history: pd.DataFrame,
        sector_histories: Mapping[str, pd.DataFrame] | None = None,
        sectors_by_ticker: Mapping[str, str] | None = None,
        universe: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        observations = build_observations_from_histories(
            stock_histories=stock_histories,
            market_history=market_history,
            sector_histories=sector_histories,
            sectors_by_ticker=sectors_by_ticker,
            mapping=self._mapping,
        )
        history_sessions_max = max((len(frame) for frame in stock_histories.values()), default=0)
        return self.evaluate_observations(
            observations,
            universe=universe or tuple(stock_histories),
            history_sessions_max=history_sessions_max,
        )

    def _abort_reasons(
        self,
        observations: Sequence[NestedModelObservation],
        *,
        coverage: Mapping[str, Any],
        history_sessions_max: int | None,
    ) -> list[str]:
        reasons: list[str] = []
        if not coverage.get("meets_minimum_coverage"):
            reasons.append(
                f"Group map coverage is {coverage.get('coverage_pct')}% of the evaluated universe; "
                f"abort threshold is {MIN_LIQUID_UNIVERSE_COVERAGE * 100:.0f}%."
            )
        if history_sessions_max is not None and history_sessions_max < MIN_HISTORY_SESSIONS_RECOMMENDED:
            reasons.append(
                f"Longest price history is {history_sessions_max} sessions; "
                f"{MIN_HISTORY_SESSIONS_RECOMMENDED} (~2y daily) is required for a full RRG walk-forward."
            )
        dates = sorted({row.as_of for row in observations})
        if len(dates) < MIN_FOLD_DATES * self._folds:
            reasons.append(
                f"Only {len(dates)} sampled cross-sections are available; "
                f"{MIN_FOLD_DATES * self._folds} weekly dates are needed for {self._folds} folds."
            )
        if len(observations) < MIN_FOLD_OBSERVATIONS * self._folds:
            reasons.append(
                f"Only {len(observations)} nested-model observations are available; "
                f"the walk-forward design expects at least {MIN_FOLD_OBSERVATIONS} rows per fold."
            )
        return reasons

    def _data_quality(
        self,
        observations: Sequence[NestedModelObservation],
        history_sessions_max: int | None,
    ) -> dict[str, Any]:
        dates = sorted({row.as_of for row in observations})
        tickers = sorted({row.ticker for row in observations})
        singleton_share = (
            sum(1 for row in observations if row.singleton_group) / len(observations)
            if observations
            else None
        )
        return {
            "observations": len(observations),
            "distinct_dates": len(dates),
            "distinct_tickers": len(tickers),
            "period_start": dates[0].isoformat() if dates else None,
            "period_end": dates[-1].isoformat() if dates else None,
            "history_sessions_max": history_sessions_max,
            "singleton_observation_share": (
                round(singleton_share, 4) if singleton_share is not None else None
            ),
            "sample_anchor": SAMPLE_ANCHOR,
        }

    def _build_folds(
        self,
        observations: Sequence[NestedModelObservation],
    ) -> list[WalkForwardFoldSpec]:
        unique_dates = sorted({row.as_of for row in observations})
        if len(unique_dates) < MIN_FOLD_DATES:
            return []
        initial_training_dates = max(MIN_FOLD_DATES, math.ceil(len(unique_dates) * 0.40))
        validation_pool = unique_dates[initial_training_dates:]
        if not validation_pool:
            return []
        blocks = _split_dates(validation_pool, min(self._folds, len(validation_pool)))
        folds: list[WalkForwardFoldSpec] = []
        for index, validation_dates in enumerate(blocks, start=1):
            validation_start = validation_dates[0]
            training_end = validation_start - timedelta(days=self._embargo_days)
            training_rows = [row for row in observations if row.as_of <= training_end]
            training_dates = {row.as_of for row in training_rows}
            eligible = len(training_rows) >= MIN_FOLD_OBSERVATIONS and len(training_dates) >= MIN_FOLD_DATES
            reason = None
            if not eligible:
                reason = "Training window is too small after the calendar embargo."
            folds.append(
                WalkForwardFoldSpec(
                    fold=index,
                    training_end=training_end,
                    validation_start=validation_start,
                    validation_end=validation_dates[-1],
                    validation_dates=tuple(validation_dates),
                    eligible=eligible,
                    ineligible_reason=reason,
                )
            )
        return folds

    def _evaluate_fold(
        self,
        observations: Sequence[NestedModelObservation],
        fold: WalkForwardFoldSpec,
        *,
        horizon_days: int,
    ) -> NestedModelFoldResult:
        target_name = f"excess_{horizon_days}d"
        validation_dates = set(fold.validation_dates)
        train_rows = [
            row
            for row in observations
            if row.as_of <= fold.training_end and row.feature_value(target_name) is not None
        ]
        validation_rows = [
            row
            for row in observations
            if row.as_of in validation_dates and row.feature_value(target_name) is not None
        ]
        if not fold.eligible:
            return NestedModelFoldResult(
                fold=fold.fold,
                horizon_days=horizon_days,
                eligible=False,
                n_train=len(train_rows),
                n_validation=len(validation_rows),
                baseline=_empty_metrics(),
                nested=_empty_metrics(),
                lift=_empty_metrics(),
                used_baseline_features=(),
                used_group_features=(),
                abort_reason=fold.ineligible_reason,
            )
        baseline_features = _usable_features(train_rows, BASELINE_FEATURES)
        group_features = _usable_features(train_rows, GROUP_FEATURES)
        if not baseline_features:
            return NestedModelFoldResult(
                fold=fold.fold,
                horizon_days=horizon_days,
                eligible=False,
                n_train=len(train_rows),
                n_validation=len(validation_rows),
                baseline=_empty_metrics(),
                nested=_empty_metrics(),
                lift=_empty_metrics(),
                used_baseline_features=(),
                used_group_features=tuple(group_features),
                abort_reason="Baseline single-name RS features are unavailable in the training window.",
            )
        if not group_features:
            return NestedModelFoldResult(
                fold=fold.fold,
                horizon_days=horizon_days,
                eligible=False,
                n_train=len(train_rows),
                n_validation=len(validation_rows),
                baseline=_empty_metrics(),
                nested=_empty_metrics(),
                lift=_empty_metrics(),
                used_baseline_features=tuple(baseline_features),
                used_group_features=(),
                abort_reason="Group RS / RRG features are unavailable in the training window.",
            )
        if len(validation_rows) < MIN_CROSS_SECTION:
            return NestedModelFoldResult(
                fold=fold.fold,
                horizon_days=horizon_days,
                eligible=False,
                n_train=len(train_rows),
                n_validation=len(validation_rows),
                baseline=_empty_metrics(),
                nested=_empty_metrics(),
                lift=_empty_metrics(),
                used_baseline_features=tuple(baseline_features),
                used_group_features=tuple(group_features),
                abort_reason="Validation cross-section is too small.",
            )
        y_train = np.array([row.feature_value(target_name) for row in train_rows], dtype=float)
        baseline_pred = _predict_ols(train_rows, validation_rows, baseline_features, y_train)
        nested_pred = _predict_ols(
            train_rows,
            validation_rows,
            (*baseline_features, *group_features),
            y_train,
        )
        realized = np.array([row.feature_value(target_name) for row in validation_rows], dtype=float)
        baseline_metrics = _metrics(baseline_pred, realized)
        nested_metrics = _metrics(nested_pred, realized)
        lift = {
            key: _subtract(nested_metrics[key], baseline_metrics[key])
            for key in PRIMARY_METRICS
        }
        return NestedModelFoldResult(
            fold=fold.fold,
            horizon_days=horizon_days,
            eligible=True,
            n_train=len(train_rows),
            n_validation=len(validation_rows),
            baseline=baseline_metrics,
            nested=nested_metrics,
            lift=lift,
            used_baseline_features=tuple(baseline_features),
            used_group_features=tuple(group_features),
        )

    def _verdict(
        self,
        fold_results: Sequence[NestedModelFoldResult],
        abort_reasons: Sequence[str],
    ) -> dict[str, Any]:
        eligible = [row for row in fold_results if row.eligible]
        metric_lifts = {
            metric: sum(
                1
                for row in eligible
                if row.lift.get(metric) is not None and float(row.lift[metric]) > 0
            )
            for metric in PRIMARY_METRICS
        }
        winning_metrics = [
            metric for metric, wins in metric_lifts.items() if wins >= 2
        ]
        if abort_reasons:
            outcome = "aborted"
        elif len(eligible) < 3:
            outcome = "aborted"
            abort_reasons = [
                *abort_reasons,
                f"Only {len(eligible)} eligible walk-forward folds were produced; 3 are required.",
            ]
        elif winning_metrics:
            outcome = "success"
        else:
            outcome = "fail"
        return {
            "outcome": outcome,
            "eligible_folds": len(eligible),
            "positive_lift_folds_by_metric": metric_lifts,
            "winning_primary_metrics": winning_metrics,
            "abort_reasons": list(abort_reasons),
            "live_surface_changed": False,
        }


def build_observations_from_histories(
    *,
    stock_histories: Mapping[str, pd.DataFrame],
    market_history: pd.DataFrame,
    sector_histories: Mapping[str, pd.DataFrame] | None = None,
    sectors_by_ticker: Mapping[str, str] | None = None,
    mapping: Mapping[str, IndustryGroupMembership] | None = None,
    sample: str = SAMPLE_ANCHOR,
) -> list[NestedModelObservation]:
    catalog = mapping if mapping is not None else INDUSTRY_GROUP_MAP
    sectors_by_ticker = {
        str(ticker).upper().strip(): str(sector or "")
        for ticker, sector in (sectors_by_ticker or {}).items()
    }
    name_frames = compute_name_feature_frames(
        {str(ticker).upper().strip(): frame for ticker, frame in stock_histories.items()},
        market_history,
        sector_histories=sector_histories,
        sectors_by_ticker=sectors_by_ticker,
    )
    memberships = {
        ticker: membership
        for ticker in name_frames
        if (membership := industry_group_for_ticker(ticker, mapping=catalog)) is not None
    }
    group_avg = compute_group_avg_rs_frame(name_frames, memberships)
    group_rank = compute_group_rank_frame(group_avg)
    rrg = compute_rrg_frame(group_avg)
    group_counts = _group_counts(memberships)
    closes = {
        ticker: _close_series(frame)
        for ticker, frame in stock_histories.items()
    }
    market_close = _close_series(market_history)

    sample_index = _sample_index(name_frames, sample)
    observations: list[NestedModelObservation] = []
    for as_of in sample_index:
        cross_section = []
        for ticker, frame in name_frames.items():
            if as_of not in frame.index:
                continue
            row = frame.loc[as_of]
            raw_strength = _optional_float(row.get("raw_strength_pct"))
            if raw_strength is None:
                continue
            cross_section.append((ticker, raw_strength, row))
        if len(cross_section) < MIN_CROSS_SECTION:
            continue
        universe_values = [raw for _, raw, _ in cross_section]
        sector_values: dict[str, list[float]] = {}
        for ticker, raw, _row in cross_section:
            sector_values.setdefault(sectors_by_ticker.get(ticker, ""), []).append(raw)
        for ticker, raw_strength, row in cross_section:
            membership = memberships.get(ticker)
            group_id = membership.group_id if membership else None
            rank_value = _lookup_asof(group_rank, group_id, as_of)
            observations.append(
                NestedModelObservation(
                    as_of=pd.Timestamp(as_of).date(),
                    ticker=ticker,
                    raw_strength_pct=raw_strength,
                    universe_percentile=_percentile(raw_strength, universe_values),
                    sector_percentile=_percentile(
                        raw_strength,
                        sector_values.get(sectors_by_ticker.get(ticker, ""), []),
                        minimum_peers=3,
                    ),
                    market_relative_pct=_optional_float(row.get("market_relative_pct")),
                    sector_relative_pct=_optional_float(row.get("sector_relative_pct")),
                    group_id=group_id,
                    group_avg_rs_pct=_lookup_asof(group_avg, group_id, as_of),
                    group_rank=rank_value,
                    group_rank_percentile=_percentile(
                        rank_value,
                        [
                            value
                            for value in (
                                _lookup_asof(group_rank, other.group_id, as_of)
                                for other in memberships.values()
                            )
                            if value is not None
                        ],
                        minimum_peers=2,
                        invert=True,
                    )
                    if rank_value is not None
                    else None,
                    rank_delta_1w=_rank_delta_asof(group_rank, group_id, as_of, RANK_LOOKBACK_SESSIONS["1w"]),
                    rank_delta_1m=_rank_delta_asof(group_rank, group_id, as_of, RANK_LOOKBACK_SESSIONS["1m"]),
                    rank_delta_3m=_rank_delta_asof(group_rank, group_id, as_of, RANK_LOOKBACK_SESSIONS["3m"]),
                    rank_delta_6m=_rank_delta_asof(group_rank, group_id, as_of, RANK_LOOKBACK_SESSIONS["6m"]),
                    rs_ratio=_lookup_asof_ffill(rrg["rs_ratio"], group_id, as_of),
                    rs_momentum=_lookup_asof_ffill(rrg["rs_momentum"], group_id, as_of),
                    excess_5d=_forward_excess(closes.get(ticker), market_close, as_of, 5),
                    excess_20d=_forward_excess(closes.get(ticker), market_close, as_of, 20),
                    excess_60d=_forward_excess(closes.get(ticker), market_close, as_of, 60),
                    singleton_group=group_counts.get(group_id, 0) <= 1 if group_id else False,
                )
            )
    return observations


def summarize_assigned_views(results: Sequence[Any]) -> dict[str, Any]:
    payload = assign_industry_group_relative_strength(results)
    payload["live_ranking_changed"] = False
    payload["applied_impact_nonzero"] = sum(
        1
        for result in results
        if getattr(getattr(result, "industry_group_rs_view", None), "applied_impact", 0)
    )
    return payload


def _close_series(history: pd.DataFrame | None) -> pd.Series:
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().sort_index()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close


def _sample_index(name_frames: Mapping[str, pd.DataFrame], sample: str) -> pd.DatetimeIndex:
    if not name_frames:
        return pd.DatetimeIndex([])
    union = pd.DatetimeIndex([])
    for frame in name_frames.values():
        union = union.union(frame.index)
    union = pd.DatetimeIndex(pd.to_datetime(union)).tz_localize(None).sort_values().unique()
    sampled = pd.Series(1, index=union).resample(sample).last().index
    return pd.DatetimeIndex([stamp for stamp in sampled if stamp in union])


def _optional_float(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    return float(value)


def _percentile(
    value: float | None,
    values: Sequence[float],
    *,
    minimum_peers: int = 5,
    invert: bool = False,
) -> float | None:
    if value is None or len(values) < minimum_peers:
        return None
    ordered = list(values)
    below = sum(candidate < value for candidate in ordered)
    equal = sum(candidate == value for candidate in ordered)
    denominator = len(ordered) - 1
    if denominator <= 0:
        return None
    mid_rank = below + (equal - 1) / 2
    percentile = mid_rank / denominator * 100.0
    if invert:
        percentile = 100.0 - percentile
    return round(percentile, 2)


def _lookup_asof(frame: pd.DataFrame, group_id: str | None, as_of: pd.Timestamp) -> float | None:
    if group_id is None or group_id not in frame.columns or as_of not in frame.index:
        return None
    return _optional_float(frame.loc[as_of, group_id])


def _lookup_asof_ffill(frame: pd.DataFrame, group_id: str | None, as_of: pd.Timestamp) -> float | None:
    if group_id is None or group_id not in frame.columns or frame.empty:
        return None
    available = frame.loc[frame.index <= as_of, group_id].dropna()
    if available.empty:
        return None
    return float(available.iloc[-1])


def _rank_delta_asof(
    frame: pd.DataFrame,
    group_id: str | None,
    as_of: pd.Timestamp,
    sessions: int,
) -> float | None:
    current = _lookup_asof(frame, group_id, as_of)
    if current is None or group_id not in frame.columns:
        return None
    history = frame.loc[frame.index <= as_of, group_id].dropna()
    if len(history) <= sessions:
        return None
    previous = float(history.iloc[-(sessions + 1)])
    return float(previous - current)


def _forward_excess(
    stock_close: pd.Series | None,
    market_close: pd.Series,
    as_of: pd.Timestamp,
    horizon: int,
) -> float | None:
    if stock_close is None or stock_close.empty or market_close.empty:
        return None
    stock_future = stock_close.loc[stock_close.index >= as_of]
    market_future = market_close.loc[market_close.index >= as_of]
    if len(stock_future) <= horizon or len(market_future) <= horizon:
        return None
    stock_start = float(stock_future.iloc[0])
    market_start = float(market_future.iloc[0])
    stock_end = float(stock_future.iloc[horizon])
    market_end = float(market_future.iloc[horizon])
    if stock_start <= 0 or market_start <= 0:
        return None
    stock_return = (stock_end / stock_start - 1.0) * 100.0
    market_return = (market_end / market_start - 1.0) * 100.0
    return stock_return - market_return


def _group_counts(memberships: Mapping[str, IndustryGroupMembership]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for membership in memberships.values():
        counts[membership.group_id] = counts.get(membership.group_id, 0) + 1
    return counts


def _usable_features(
    rows: Sequence[NestedModelObservation],
    names: Sequence[str],
) -> list[str]:
    usable: list[str] = []
    if not rows:
        return usable
    for name in names:
        coverage = sum(row.feature_value(name) is not None for row in rows) / len(rows)
        if coverage >= MIN_FEATURE_COVERAGE:
            usable.append(name)
    return usable


def _predict_ols(
    train_rows: Sequence[NestedModelObservation],
    test_rows: Sequence[NestedModelObservation],
    features: Sequence[str],
    y_train: np.ndarray,
) -> np.ndarray:
    x_train = _feature_matrix(train_rows, features)
    x_test = _feature_matrix(test_rows, features)
    train_mean = np.nanmean(x_train, axis=0)
    train_std = np.nanstd(x_train, axis=0)
    train_std = np.where(train_std == 0, 1.0, train_std)
    x_train = np.where(np.isnan(x_train), np.broadcast_to(train_mean, x_train.shape), x_train)
    x_test = np.where(np.isnan(x_test), np.broadcast_to(train_mean, x_test.shape), x_test)
    x_train = (x_train - train_mean) / train_std
    x_test = (x_test - train_mean) / train_std
    design_train = np.column_stack([np.ones(len(x_train)), x_train])
    design_test = np.column_stack([np.ones(len(x_test)), x_test])
    beta, *_ = np.linalg.lstsq(design_train, y_train, rcond=None)
    return design_test @ beta


def _feature_matrix(
    rows: Sequence[NestedModelObservation],
    features: Sequence[str],
) -> np.ndarray:
    return np.array(
        [[row.feature_value(name) for name in features] for row in rows],
        dtype=float,
    )


def _metrics(predicted: np.ndarray, realized: np.ndarray) -> dict[str, float | None]:
    if len(predicted) < MIN_CROSS_SECTION:
        return _empty_metrics()
    return {
        "spearman_ic": _spearman_ic(predicted, realized),
        "top_decile_hit_rate": round(_top_decile_hit_rate(predicted, realized), 6),
    }


def _spearman_ic(predicted: np.ndarray, realized: np.ndarray) -> float | None:
    if np.unique(predicted).size < 2 or np.unique(realized).size < 2:
        return None
    ic = pd.Series(predicted).rank().corr(pd.Series(realized).rank(), method="pearson")
    if ic is None or pd.isna(ic):
        return None
    return round(float(ic), 6)


def _top_decile_hit_rate(predicted: np.ndarray, realized: np.ndarray) -> float:
    count = len(predicted)
    top_k = max(1, int(round(count * 0.10)))
    predicted_top = set(np.argsort(predicted)[-top_k:])
    realized_top = set(np.argsort(realized)[-top_k:])
    return len(predicted_top & realized_top) / top_k


def _empty_metrics() -> dict[str, float | None]:
    return {"spearman_ic": None, "top_decile_hit_rate": None}


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 6)


def _split_dates(dates: Sequence[date], parts: int) -> list[list[date]]:
    if parts <= 0 or not dates:
        return []
    size = math.ceil(len(dates) / parts)
    return [list(dates[index : index + size]) for index in range(0, len(dates), size)][:parts]


__all__ = [
    "BASELINE_FEATURES",
    "GROUP_FEATURES",
    "IndustryGroupRsEvalService",
    "NestedModelObservation",
    "PRIMARY_HORIZON_DAYS",
    "PRIMARY_METRICS",
    "build_observations_from_histories",
    "summarize_assigned_views",
]
