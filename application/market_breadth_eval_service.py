from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from application.calibration_research_service import WALK_FORWARD_EMBARGO_DAYS, WALK_FORWARD_FOLDS
from config.market_breadth import (
    REDUNDANCY_IC_EPSILON,
    REDUNDANCY_R2_EPSILON,
    breadth_recipe_manifest,
)
from config.performance import PERFORMANCE_DB_FILE
from config.universe import DEFAULT_STOCK_UNIVERSE
from domain.scoring.market_breadth import (
    BreadthPanel,
    GateStatus,
    build_breadth_panel,
    build_market_breadth_view,
)
from storage.repositories.outcome_repository import OutcomeRepository


PRIMARY_METRICS = ("spearman_ic", "top_decile_hit_rate")
RS_PERCENTILE_FEATURES = (
    "rs_universe_percentile",
    "rs_sector_percentile",
    "rs_score",
    "daily_mean_universe_percentile",
    "daily_median_universe_percentile",
)
BREADTH_FEATURES = (
    "pct_above_20dma",
    "pct_above_50dma",
    "pct_above_200dma",
    "ad_line_change_nd",
    "up_down_volume_ratio",
    "spy_minus_equal_weight_pct",
)
MIN_FOLD_DATES = 4
MIN_FOLD_HITS = 12
MIN_GATED_FOLD_HITS = 8
MIN_FEATURE_COVERAGE = 0.50


@dataclass(frozen=True)
class ShadowHitObservation:
    signal_id: str
    ticker: str
    signal_date: date
    realized_return_pct: float
    rs_score: float | None
    rs_universe_percentile: float | None
    rs_sector_percentile: float | None
    earnings_score: float | None
    form4_impact: float | None
    signed_shadow_score: float | None
    daily_mean_universe_percentile: float | None = None
    daily_median_universe_percentile: float | None = None
    pct_above_20dma: float | None = None
    pct_above_50dma: float | None = None
    pct_above_200dma: float | None = None
    ad_line_change_nd: float | None = None
    up_down_volume_ratio: float | None = None
    spy_minus_equal_weight_pct: float | None = None
    gate_status: GateStatus = "unknown"

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


class MarketBreadthEvalService:
    """Offline breadth-gate harness. Never writes live scores or recommendations."""

    def __init__(
        self,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Path | None = None,
        *,
        hits: Sequence[ShadowHitObservation] | None = None,
        folds: int = WALK_FORWARD_FOLDS,
        embargo_days: int = WALK_FORWARD_EMBARGO_DAYS,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._provided_hits = tuple(hits) if hits is not None else None
        self._folds = max(int(folds), 1)
        self._embargo_days = max(int(embargo_days), 0)

    def evaluate_panel(
        self,
        panel: BreadthPanel,
        hits: Sequence[ShadowHitObservation] | None = None,
    ) -> dict[str, Any]:
        resolved_hits = self._with_panel_features(hits if hits is not None else self._load_hits(), panel)
        abort_reasons = list(panel.abort_reasons)
        abort_reasons.extend(self._hit_abort_reasons(resolved_hits))
        folds = self._build_folds(resolved_hits)
        gate_results = [self._evaluate_gate_fold(resolved_hits, fold) for fold in folds]
        nested_results = [self._evaluate_nested_fold(resolved_hits, fold) for fold in folds]
        view = build_market_breadth_view(panel)
        verdict = self._verdict(gate_results, nested_results, abort_reasons)
        return {
            "status": "research_only",
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_recommendation_changes": False,
                "live_ranking_changes": False,
                "message": (
                    "Universe participation is a shadow regime gate, not a buy list. "
                    "This harness never writes production scores or recommendations."
                ),
            },
            "pre_registration": {
                "recipe": breadth_recipe_manifest(),
                "primary_metrics": list(PRIMARY_METRICS),
                "success_rule": (
                    "The frozen gate improves at least one primary metric (Spearman IC or "
                    "top-decile hit-rate) versus ungated shadow hits in at least 2 of 3 "
                    "walk-forward folds, panel %above-MA coverage averages at least 80%, "
                    "and nested breadth features are not redundant with RS-percentile aggregates."
                ),
                "gate_is_fitted": False,
                "sensitivity_is_appendix_only": True,
            },
            "panel": panel.to_dict(),
            "latest_view": view.to_dict(),
            "data_quality": self._data_quality(resolved_hits, panel),
            "abort_reasons": abort_reasons,
            "walk_forward_folds": [asdict(fold) for fold in folds],
            "gate_fold_results": gate_results,
            "nested_fold_results": nested_results,
            "verdict": verdict,
        }

    def evaluate_price_panel(
        self,
        *,
        stock_histories: Mapping[str, pd.DataFrame],
        spy_history: pd.DataFrame,
        rsp_history: pd.DataFrame | None = None,
        hits: Sequence[ShadowHitObservation] | None = None,
        universe: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        panel = build_breadth_panel(
            stock_histories,
            spy_history,
            universe=universe or tuple(DEFAULT_STOCK_UNIVERSE),
            rsp_history=rsp_history,
        )
        return self.evaluate_panel(panel, hits=hits)

    def evaluate_from_store(
        self,
        *,
        stock_histories: Mapping[str, pd.DataFrame],
        spy_history: pd.DataFrame,
        rsp_history: pd.DataFrame | None = None,
        universe: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        return self.evaluate_price_panel(
            stock_histories=stock_histories,
            spy_history=spy_history,
            rsp_history=rsp_history,
            hits=self._load_hits(),
            universe=universe,
        )

    def _load_hits(self) -> list[ShadowHitObservation]:
        if self._provided_hits is not None:
            return list(self._provided_hits)
        self._outcome_repository.ensure_schema()
        hits: list[ShadowHitObservation] = []
        for row in self._outcome_repository.list_calibration_observations():
            parsed = shadow_hit_from_row(row)
            if parsed is not None:
                hits.append(parsed)
        return hits

    def _with_panel_features(
        self,
        hits: Sequence[ShadowHitObservation],
        panel: BreadthPanel,
    ) -> list[ShadowHitObservation]:
        daily_rs = _daily_rs_aggregates(hits)
        joined: list[ShadowHitObservation] = []
        for hit in hits:
            snapshot = panel.snapshot_on(hit.signal_date)
            mean_pct, median_pct = daily_rs.get(hit.signal_date, (None, None))
            joined.append(
                ShadowHitObservation(
                    **{
                        **asdict(hit),
                        "daily_mean_universe_percentile": mean_pct,
                        "daily_median_universe_percentile": median_pct,
                        "pct_above_20dma": snapshot.pct_above_20dma if snapshot else None,
                        "pct_above_50dma": snapshot.pct_above_50dma if snapshot else None,
                        "pct_above_200dma": snapshot.pct_above_200dma if snapshot else None,
                        "ad_line_change_nd": snapshot.ad_line_change_nd if snapshot else None,
                        "up_down_volume_ratio": snapshot.up_down_volume_ratio if snapshot else None,
                        "spy_minus_equal_weight_pct": snapshot.spy_minus_equal_weight_pct if snapshot else None,
                        "gate_status": snapshot.gate.status if snapshot else "unknown",
                    }
                )
            )
        return joined

    def _hit_abort_reasons(self, hits: Sequence[ShadowHitObservation]) -> list[str]:
        reasons: list[str] = []
        dates = {row.signal_date for row in hits}
        usable = [row for row in hits if row.signed_shadow_score is not None]
        if len(usable) < MIN_FOLD_HITS * self._folds:
            reasons.append(
                f"Only {len(usable)} signed shadow hits are available; "
                f"{MIN_FOLD_HITS} per fold are required for a walk-forward claim."
            )
        if len(dates) < MIN_FOLD_DATES * self._folds:
            reasons.append(
                f"Only {len(dates)} distinct signal dates are available; "
                f"{MIN_FOLD_DATES * self._folds} are needed for {self._folds} folds."
            )
        return reasons

    def _data_quality(
        self,
        hits: Sequence[ShadowHitObservation],
        panel: BreadthPanel,
    ) -> dict[str, Any]:
        dates = sorted({row.signal_date for row in hits})
        families = {
            "relative_strength": sum(row.rs_score is not None or row.rs_universe_percentile is not None for row in hits),
            "earnings": sum(row.earnings_score is not None for row in hits),
            "form4": sum(row.form4_impact is not None for row in hits),
        }
        return {
            "shadow_hits": len(hits),
            "signed_shadow_hits": sum(row.signed_shadow_score is not None for row in hits),
            "gated_open_hits": sum(row.gate_status == "open" for row in hits),
            "distinct_tickers": len({row.ticker for row in hits}),
            "distinct_signal_dates": len(dates),
            "period_start": dates[0].isoformat() if dates else None,
            "period_end": dates[-1].isoformat() if dates else None,
            "family_coverage": families,
            "history_sessions_max": panel.history_sessions_max,
            "rsp_available": panel.rsp_available,
            "cap_vs_equal_weight_proxy": panel.cap_vs_equal_weight_proxy,
        }

    def _build_folds(
        self,
        hits: Sequence[ShadowHitObservation],
    ) -> list[WalkForwardFoldSpec]:
        unique_dates = sorted({row.signal_date for row in hits})
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
            training_rows = [row for row in hits if row.signal_date <= training_end]
            training_dates = {row.signal_date for row in training_rows}
            eligible = len(training_rows) >= MIN_FOLD_HITS and len(training_dates) >= MIN_FOLD_DATES
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

    def _evaluate_gate_fold(
        self,
        hits: Sequence[ShadowHitObservation],
        fold: WalkForwardFoldSpec,
    ) -> dict[str, Any]:
        validation = [
            row
            for row in hits
            if row.signal_date in set(fold.validation_dates) and row.signed_shadow_score is not None
        ]
        gated = [row for row in validation if row.gate_status == "open"]
        if not fold.eligible:
            return _empty_gate_fold(fold, validation, gated, abort_reason=fold.ineligible_reason)
        if len(validation) < MIN_FOLD_HITS:
            return _empty_gate_fold(
                fold,
                validation,
                gated,
                abort_reason="Ungated validation sample is too small.",
            )
        if len(gated) < MIN_GATED_FOLD_HITS:
            return _empty_gate_fold(
                fold,
                validation,
                gated,
                abort_reason="Gated validation sample is too small.",
            )
        ungated_metrics = _score_metrics(validation)
        gated_metrics = _score_metrics(gated)
        lift = {
            metric: _subtract(gated_metrics[metric], ungated_metrics[metric])
            for metric in PRIMARY_METRICS
        }
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_ungated": len(validation),
            "n_gated": len(gated),
            "ungated": ungated_metrics,
            "gated": gated_metrics,
            "lift": lift,
            "abort_reason": None,
        }

    def _evaluate_nested_fold(
        self,
        hits: Sequence[ShadowHitObservation],
        fold: WalkForwardFoldSpec,
    ) -> dict[str, Any]:
        train_rows = [
            row
            for row in hits
            if row.signal_date <= fold.training_end and math.isfinite(row.realized_return_pct)
        ]
        validation_rows = [
            row
            for row in hits
            if row.signal_date in set(fold.validation_dates) and math.isfinite(row.realized_return_pct)
        ]
        if not fold.eligible:
            return _empty_nested_fold(fold, train_rows, validation_rows, abort_reason=fold.ineligible_reason)
        baseline_features = _usable_features(train_rows, RS_PERCENTILE_FEATURES)
        breadth_features = _usable_features(train_rows, BREADTH_FEATURES)
        if not baseline_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                abort_reason="RS-percentile aggregate features are unavailable in the training window.",
            )
        if not breadth_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                abort_reason="Breadth features are unavailable in the training window.",
            )
        if len(validation_rows) < MIN_FOLD_HITS:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                used_breadth_features=tuple(breadth_features),
                abort_reason="Nested-model validation sample is too small.",
            )
        y_train = np.array([row.realized_return_pct for row in train_rows], dtype=float)
        baseline_pred = _predict_ols(train_rows, validation_rows, baseline_features, y_train)
        nested_pred = _predict_ols(
            train_rows,
            validation_rows,
            (*baseline_features, *breadth_features),
            y_train,
        )
        realized = np.array([row.realized_return_pct for row in validation_rows], dtype=float)
        baseline_metrics = _prediction_metrics(baseline_pred, realized)
        nested_metrics = _prediction_metrics(nested_pred, realized)
        lift = {
            key: _subtract(nested_metrics[key], baseline_metrics[key])
            for key in (*PRIMARY_METRICS, "r_squared")
        }
        redundant = _is_redundant(lift)
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_train": len(train_rows),
            "n_validation": len(validation_rows),
            "baseline": baseline_metrics,
            "nested": nested_metrics,
            "lift": lift,
            "redundant": redundant,
            "used_baseline_features": list(baseline_features),
            "used_breadth_features": list(breadth_features),
            "abort_reason": None,
        }

    def _verdict(
        self,
        gate_results: Sequence[Mapping[str, Any]],
        nested_results: Sequence[Mapping[str, Any]],
        abort_reasons: Sequence[str],
    ) -> dict[str, Any]:
        eligible_gate = [row for row in gate_results if row.get("eligible")]
        eligible_nested = [row for row in nested_results if row.get("eligible")]
        metric_lifts = {
            metric: sum(
                1
                for row in eligible_gate
                if row.get("lift", {}).get(metric) is not None and float(row["lift"][metric]) > 0
            )
            for metric in PRIMARY_METRICS
        }
        winning_metrics = [metric for metric, wins in metric_lifts.items() if wins >= 2]
        nested_ic_lifts = [
            float(row["lift"]["spearman_ic"])
            for row in eligible_nested
            if row.get("lift", {}).get("spearman_ic") is not None
        ]
        nested_r2_lifts = [
            float(row["lift"]["r_squared"])
            for row in eligible_nested
            if row.get("lift", {}).get("r_squared") is not None
        ]
        mean_nested_ic_lift = (
            round(sum(nested_ic_lifts) / len(nested_ic_lifts), 6) if nested_ic_lifts else None
        )
        mean_nested_r2_lift = (
            round(sum(nested_r2_lifts) / len(nested_r2_lifts), 6) if nested_r2_lifts else None
        )
        redundant = (
            mean_nested_ic_lift is not None
            and mean_nested_r2_lift is not None
            and abs(mean_nested_ic_lift) < REDUNDANCY_IC_EPSILON
            and abs(mean_nested_r2_lift) < REDUNDANCY_R2_EPSILON
        )
        reasons = list(abort_reasons)
        if reasons:
            outcome = "aborted"
        elif len(eligible_gate) < 3:
            outcome = "aborted"
            reasons.append(
                f"Only {len(eligible_gate)} eligible gate folds were produced; 3 are required."
            )
        elif redundant:
            outcome = "fail"
            reasons.append(
                "Nested breadth features are redundant with RS-percentile aggregates "
                f"(mean IC lift {mean_nested_ic_lift}, mean R² lift {mean_nested_r2_lift})."
            )
        elif winning_metrics:
            outcome = "success"
        else:
            outcome = "fail"
            reasons.append("The frozen gate did not improve a primary metric in at least 2 of 3 folds.")
        return {
            "outcome": outcome,
            "eligible_gate_folds": len(eligible_gate),
            "eligible_nested_folds": len(eligible_nested),
            "positive_gate_lift_folds_by_metric": metric_lifts,
            "winning_primary_metrics": winning_metrics,
            "mean_nested_ic_lift": mean_nested_ic_lift,
            "mean_nested_r2_lift": mean_nested_r2_lift,
            "breadth_redundant_with_rs_percentiles": redundant,
            "abort_reasons": reasons,
            "live_surface_changed": False,
        }


def shadow_hit_from_row(row: Mapping[str, Any]) -> ShadowHitObservation | None:
    payload = dict(row)
    realized = payload.get("realized_return_pct")
    if realized is None:
        return None
    try:
        realized_return = float(realized)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(realized_return):
        return None
    snapshot = _snapshot(payload.get("feature_snapshot_json"))
    relative = snapshot.get("relative_strength") if isinstance(snapshot.get("relative_strength"), dict) else {}
    earnings = (
        snapshot.get("earnings_intelligence")
        if isinstance(snapshot.get("earnings_intelligence"), dict)
        else {}
    )
    rs_score = _optional_float(relative.get("score"))
    universe_percentile = _optional_float(relative.get("universe_percentile"))
    sector_percentile = _optional_float(relative.get("sector_percentile"))
    earnings_score = _optional_float(earnings.get("score"))
    form4_impact = _form4_impact(snapshot)
    signed = signed_shadow_score(
        rs_score=rs_score,
        rs_universe_percentile=universe_percentile,
        earnings_score=earnings_score,
        form4_impact=form4_impact,
    )
    if signed is None:
        return None
    ticker = str(payload.get("ticker") or "UNKNOWN").upper().strip()
    return ShadowHitObservation(
        signal_id=str(payload.get("signal_id") or ""),
        ticker=ticker,
        signal_date=_parse_date(payload.get("created_at")),
        realized_return_pct=realized_return,
        rs_score=rs_score,
        rs_universe_percentile=universe_percentile,
        rs_sector_percentile=sector_percentile,
        earnings_score=earnings_score,
        form4_impact=form4_impact,
        signed_shadow_score=signed,
    )


def signed_shadow_score(
    *,
    rs_score: float | None,
    rs_universe_percentile: float | None,
    earnings_score: float | None,
    form4_impact: float | None,
) -> float | None:
    parts: list[float] = []
    if rs_universe_percentile is not None:
        parts.append(rs_universe_percentile - 50.0)
    elif rs_score is not None:
        parts.append(rs_score - 50.0)
    if earnings_score is not None:
        parts.append(earnings_score - 50.0)
    if form4_impact is not None:
        parts.append(form4_impact)
    if not parts:
        return None
    return sum(parts) / len(parts)


def _form4_impact(snapshot: Mapping[str, Any]) -> float | None:
    alternative = snapshot.get("alternative_signal")
    if not isinstance(alternative, dict):
        return None
    components = alternative.get("components") or []
    for component in components:
        if isinstance(component, dict) and component.get("key") == "sec_events":
            return _optional_float(component.get("modeled_impact"))
    return None


def _snapshot(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)
    return date.fromisoformat(text[:10])


def _daily_rs_aggregates(
    hits: Sequence[ShadowHitObservation],
) -> dict[date, tuple[float | None, float | None]]:
    grouped: dict[date, list[float]] = {}
    for hit in hits:
        if hit.rs_universe_percentile is None:
            continue
        grouped.setdefault(hit.signal_date, []).append(float(hit.rs_universe_percentile))
    payload: dict[date, tuple[float | None, float | None]] = {}
    for signal_date, values in grouped.items():
        ordered = sorted(values)
        mean = sum(ordered) / len(ordered)
        mid = len(ordered) // 2
        median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
        payload[signal_date] = (mean, median)
    return payload


def _score_metrics(rows: Sequence[ShadowHitObservation]) -> dict[str, float | None]:
    predicted = np.array([row.signed_shadow_score for row in rows], dtype=float)
    realized = np.array([row.realized_return_pct for row in rows], dtype=float)
    return {
        "spearman_ic": _spearman_ic(predicted, realized),
        "top_decile_hit_rate": round(_top_decile_hit_rate(predicted, realized), 6),
        "hit_rate": round(float(np.mean(realized > 0)), 6),
        "n": len(rows),
    }


def _prediction_metrics(predicted: np.ndarray, realized: np.ndarray) -> dict[str, float | None]:
    return {
        "spearman_ic": _spearman_ic(predicted, realized),
        "top_decile_hit_rate": round(_top_decile_hit_rate(predicted, realized), 6),
        "r_squared": _r_squared(predicted, realized),
        "n": int(len(realized)),
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
    order = np.argsort(predicted)
    selected = realized[order[-top_k:]]
    return float(np.mean(selected > 0)) if len(selected) else 0.0


def _r_squared(predicted: np.ndarray, realized: np.ndarray) -> float | None:
    if len(realized) < 3:
        return None
    residual = realized - predicted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((realized - np.mean(realized)) ** 2))
    if ss_tot <= 0:
        return None
    return round(1.0 - ss_res / ss_tot, 6)


def _usable_features(
    rows: Sequence[ShadowHitObservation],
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
    train_rows: Sequence[ShadowHitObservation],
    test_rows: Sequence[ShadowHitObservation],
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
    rows: Sequence[ShadowHitObservation],
    features: Sequence[str],
) -> np.ndarray:
    return np.array(
        [[row.feature_value(name) for name in features] for row in rows],
        dtype=float,
    )


def _is_redundant(lift: Mapping[str, float | None]) -> bool:
    ic_lift = lift.get("spearman_ic")
    r2_lift = lift.get("r_squared")
    if ic_lift is None or r2_lift is None:
        return False
    return abs(float(ic_lift)) < REDUNDANCY_IC_EPSILON and abs(float(r2_lift)) < REDUNDANCY_R2_EPSILON


def _empty_gate_fold(
    fold: WalkForwardFoldSpec,
    validation: Sequence[ShadowHitObservation],
    gated: Sequence[ShadowHitObservation],
    *,
    abort_reason: str | None,
) -> dict[str, Any]:
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_ungated": len(validation),
        "n_gated": len(gated),
        "ungated": {"spearman_ic": None, "top_decile_hit_rate": None, "hit_rate": None, "n": len(validation)},
        "gated": {"spearman_ic": None, "top_decile_hit_rate": None, "hit_rate": None, "n": len(gated)},
        "lift": {"spearman_ic": None, "top_decile_hit_rate": None},
        "abort_reason": abort_reason,
    }


def _empty_nested_fold(
    fold: WalkForwardFoldSpec,
    train_rows: Sequence[ShadowHitObservation],
    validation_rows: Sequence[ShadowHitObservation],
    *,
    abort_reason: str | None,
    used_baseline_features: tuple[str, ...] = (),
    used_breadth_features: tuple[str, ...] = (),
) -> dict[str, Any]:
    empty = {"spearman_ic": None, "top_decile_hit_rate": None, "r_squared": None, "n": 0}
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_train": len(train_rows),
        "n_validation": len(validation_rows),
        "baseline": empty,
        "nested": empty,
        "lift": {"spearman_ic": None, "top_decile_hit_rate": None, "r_squared": None},
        "redundant": False,
        "used_baseline_features": list(used_baseline_features),
        "used_breadth_features": list(used_breadth_features),
        "abort_reason": abort_reason,
    }


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 6)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _split_dates(dates: Sequence[date], parts: int) -> list[list[date]]:
    if parts <= 0 or not dates:
        return []
    size = math.ceil(len(dates) / parts)
    return [list(dates[index : index + size]) for index in range(0, len(dates), size)][:parts]


__all__ = [
    "BREADTH_FEATURES",
    "PRIMARY_METRICS",
    "RS_PERCENTILE_FEATURES",
    "MarketBreadthEvalService",
    "ShadowHitObservation",
    "signed_shadow_score",
    "shadow_hit_from_row",
]
