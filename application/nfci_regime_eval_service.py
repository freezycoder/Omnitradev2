from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence
from typing import assert_never

import numpy as np
import pandas as pd

from application.calibration_research_service import WALK_FORWARD_EMBARGO_DAYS, WALK_FORWARD_FOLDS
from config.nfci_regime import (
    ICE_REDISTRIBUTION_NOTICE,
    REDUNDANCY_IC_EPSILON,
    REDUNDANCY_R2_EPSILON,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    nfci_recipe_manifest,
)
from config.performance import MIN_LONG_TERM_SCAN_SCORE, PERFORMANCE_DB_FILE
from config.thresholds import SCANNER_RULES
from domain.scoring.nfci_regime import (
    GateStatus,
    HyKeepPanel,
    NfciPanel,
    build_hy_keep_panel,
    build_nfci_panel,
    build_nfci_regime_view,
)
from providers.macro.nfci_client import NfciSeriesBundle
from storage.repositories.outcome_repository import OutcomeRepository


PRIMARY_METRICS = ("sharpe", "max_drawdown")
VOL_FEATURES = ("spy_realized_vol_20d",)
HY_FEATURES = ("hy_oas", "hy_oas_d20_bp", "hy_oas_d5_bp", "hy_ig_gap")
NFCI_FEATURES = ("nfci_level", "nfci_d4w", "nfci_rising_streak")
BREADTH_FEATURES = ("pct_above_50dma",)
MIN_FOLD_DATES = 4
MIN_FOLD_HITS = 12
MIN_GATED_FOLD_DAYS = 4
MIN_FEATURE_COVERAGE = 0.50
LONG_BIASED_LABELS = SCANNER_RULES.long_term_labels
GATE_ARMS = ("ungated", "hy_oas_only", "nfci_only", "hy_plus_nfci")
NESTED_ARMS = ("baseline", "hy_only", "nfci_only", "hy_plus_nfci")


@dataclass(frozen=True)
class LongScreenObservation:
    signal_id: str
    ticker: str
    signal_date: date
    realized_return_pct: float
    long_term_score: float
    recommendation_label: str
    strategy_family: str
    spy_realized_vol_20d: float | None = None
    hy_oas: float | None = None
    hy_oas_d20_bp: float | None = None
    hy_oas_d5_bp: float | None = None
    hy_ig_gap: float | None = None
    nfci_level: float | None = None
    nfci_d4w: float | None = None
    nfci_rising_streak: float | None = None
    pct_above_50dma: float | None = None
    hy_gate: GateStatus = "unknown"
    hy_weight: float | None = None
    nfci_gate: GateStatus = "unknown"
    nfci_weight: float | None = None
    breadth_gate: str | None = None

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


class NfciRegimeEvalService:
    """Offline NFCI nested-gate harness. Never writes live scores or recommendations."""

    def __init__(
        self,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Any | None = None,
        *,
        hits: Sequence[LongScreenObservation] | None = None,
        folds: int = WALK_FORWARD_FOLDS,
        embargo_days: int = WALK_FORWARD_EMBARGO_DAYS,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._provided_hits = tuple(hits) if hits is not None else None
        self._folds = max(int(folds), 1)
        self._embargo_days = max(int(embargo_days), 0)

    def evaluate_panels(
        self,
        nfci_panel: NfciPanel,
        hy_panel: HyKeepPanel,
        hits: Sequence[LongScreenObservation] | None = None,
        *,
        breadth_status_by_date: Mapping[date, str] | None = None,
    ) -> dict[str, Any]:
        resolved_hits = self._with_panel_features(
            hits if hits is not None else self._load_hits(),
            nfci_panel,
            hy_panel,
            breadth_status_by_date=breadth_status_by_date,
        )
        abort_reasons = list(nfci_panel.abort_reasons)
        abort_reasons.extend(hy_panel.abort_reasons)
        abort_reasons.extend(self._hit_abort_reasons(resolved_hits))
        hy_available = not hy_panel.abort_reasons and hy_panel.hy_count > 0
        folds = self._build_folds(resolved_hits)
        comparators = [
            self._evaluate_gate_fold(resolved_hits, fold, hy_available=hy_available)
            for fold in folds
        ]
        nested_results = [
            self._evaluate_nested_fold(
                resolved_hits,
                fold,
                hy_available=hy_available,
                breadth_available=breadth_status_by_date is not None,
            )
            for fold in folds
        ]
        view = build_nfci_regime_view(nfci_panel)
        verdict = self._verdict(
            comparators,
            nested_results,
            abort_reasons,
            hy_available=hy_available,
            breadth_available=breadth_status_by_date is not None,
        )
        return {
            "status": "research_only",
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_recommendation_changes": False,
                "live_ranking_changes": False,
                "is_stock_picker": False,
                "message": (
                    "NFCI is a shadow financial-conditions regime gate that throttles "
                    "long-screen aggressiveness. This harness never writes production "
                    "scores or recommendations."
                ),
            },
            "pre_registration": {
                "recipe": nfci_recipe_manifest(),
                "hy_keep_comparator": hy_keep_recipe_manifest(),
                "primary_metrics": list(PRIMARY_METRICS),
                "gate_arms": list(GATE_ARMS),
                "nested_arms": list(NESTED_ARMS),
                "success_rule": (
                    "NFCI adds incremental gated performance (HY+NFCI vs HY OAS alone) "
                    "on Sharpe or max drawdown, or incremental nested IC/R² versus HY "
                    "OAS, in at least 2 of 3 walk-forward folds."
                ),
                "kill_switch": (
                    "KILL as redundant with KEEP HY OAS when mean incremental IC and R² "
                    f"versus HY-only sit inside ±{REDUNDANCY_IC_EPSILON} / "
                    f"±{REDUNDANCY_R2_EPSILON} and HY+NFCI shows no primary-metric "
                    "gated lift versus HY OAS alone."
                ),
                "gate_is_fitted": False,
                "anfci_in_v1": False,
            },
            "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
            "nfci_panel": nfci_panel.to_dict(),
            "hy_keep_panel": hy_panel.to_dict(),
            "latest_view": view.to_dict(),
            "data_quality": self._data_quality(
                resolved_hits,
                nfci_panel,
                hy_panel,
                breadth_status_by_date,
            ),
            "abort_reasons": abort_reasons,
            "walk_forward_folds": [asdict(fold) for fold in folds],
            "gate_fold_results": comparators,
            "nested_fold_results": nested_results,
            "verdict": verdict,
        }

    def evaluate_bundle(
        self,
        bundle: NfciSeriesBundle,
        *,
        spy_history: pd.DataFrame | None = None,
        hits: Sequence[LongScreenObservation] | None = None,
        breadth_status_by_date: Mapping[date, str] | None = None,
    ) -> dict[str, Any]:
        nfci_panel = build_nfci_panel(bundle, spy_history=spy_history)
        hy_panel = build_hy_keep_panel(bundle)
        return self.evaluate_panels(
            nfci_panel,
            hy_panel,
            hits=hits,
            breadth_status_by_date=breadth_status_by_date,
        )

    def _load_hits(self) -> list[LongScreenObservation]:
        if self._provided_hits is not None:
            return list(self._provided_hits)
        self._outcome_repository.ensure_schema()
        hits: list[LongScreenObservation] = []
        for row in self._outcome_repository.list_long_term_screen_observations():
            parsed = long_screen_from_row(row)
            if parsed is not None:
                hits.append(parsed)
        return hits

    def _with_panel_features(
        self,
        hits: Sequence[LongScreenObservation],
        nfci_panel: NfciPanel,
        hy_panel: HyKeepPanel,
        *,
        breadth_status_by_date: Mapping[date, str] | None,
    ) -> list[LongScreenObservation]:
        joined: list[LongScreenObservation] = []
        for hit in hits:
            nfci_snapshot = nfci_panel.snapshot_on(hit.signal_date)
            hy_snapshot = hy_panel.snapshot_on(hit.signal_date)
            nfci_gate: GateStatus = nfci_snapshot.gate.status if nfci_snapshot else "unknown"
            hy_gate: GateStatus = hy_snapshot.gate.status if hy_snapshot else "unknown"
            breadth_gate = None
            if breadth_status_by_date is not None:
                breadth_gate = breadth_status_by_date.get(hit.signal_date, "unknown")
            joined.append(
                replace(
                    hit,
                    spy_realized_vol_20d=(
                        nfci_snapshot.spy_realized_vol_20d
                        if nfci_snapshot and nfci_snapshot.spy_realized_vol_20d is not None
                        else hit.spy_realized_vol_20d
                    ),
                    hy_oas=hy_snapshot.hy_oas if hy_snapshot else hit.hy_oas,
                    hy_oas_d20_bp=hy_snapshot.hy_oas_d20_bp if hy_snapshot else hit.hy_oas_d20_bp,
                    hy_oas_d5_bp=hy_snapshot.hy_oas_d5_bp if hy_snapshot else hit.hy_oas_d5_bp,
                    hy_ig_gap=hy_snapshot.hy_ig_gap if hy_snapshot else hit.hy_ig_gap,
                    nfci_level=nfci_snapshot.nfci if nfci_snapshot else hit.nfci_level,
                    nfci_d4w=nfci_snapshot.nfci_d4w if nfci_snapshot else hit.nfci_d4w,
                    nfci_rising_streak=(
                        float(nfci_snapshot.rising_streak) if nfci_snapshot else hit.nfci_rising_streak
                    ),
                    hy_gate=hy_gate,
                    hy_weight=hy_snapshot.gate.throttle_weight if hy_snapshot else None,
                    nfci_gate=nfci_gate,
                    nfci_weight=nfci_snapshot.gate.throttle_weight if nfci_snapshot else None,
                    breadth_gate=breadth_gate,
                )
            )
        return joined

    def _hit_abort_reasons(self, hits: Sequence[LongScreenObservation]) -> list[str]:
        reasons: list[str] = []
        dates = {row.signal_date for row in hits}
        if len(hits) < MIN_FOLD_HITS * self._folds:
            reasons.append(
                f"Only {len(hits)} long-biased screen hits are available; "
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
        hits: Sequence[LongScreenObservation],
        nfci_panel: NfciPanel,
        hy_panel: HyKeepPanel,
        breadth_status_by_date: Mapping[date, str] | None,
    ) -> dict[str, Any]:
        dates = sorted({row.signal_date for row in hits})
        return {
            "long_screen_hits": len(hits),
            "distinct_tickers": len({row.ticker for row in hits}),
            "distinct_signal_dates": len(dates),
            "period_start": dates[0].isoformat() if dates else None,
            "period_end": dates[-1].isoformat() if dates else None,
            "nfci_full_hits": sum(row.nfci_gate == "full" for row in hits),
            "nfci_throttle_hits": sum(row.nfci_gate == "throttle" for row in hits),
            "nfci_unknown_hits": sum(row.nfci_gate == "unknown" for row in hits),
            "hy_full_hits": sum(row.hy_gate == "full" for row in hits),
            "hy_throttle_hits": sum(row.hy_gate == "throttle" for row in hits),
            "hy_unknown_hits": sum(row.hy_gate == "unknown" for row in hits),
            "hy_keep_available": not hy_panel.abort_reasons and hy_panel.hy_count > 0,
            "breadth_keep_shipped": breadth_status_by_date is not None,
            "nfci_history_weeks": nfci_panel.history_weeks,
            "series_source": nfci_panel.source,
            "join_on": "release_date",
        }

    def _build_folds(self, hits: Sequence[LongScreenObservation]) -> list[WalkForwardFoldSpec]:
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
        hits: Sequence[LongScreenObservation],
        fold: WalkForwardFoldSpec,
        *,
        hy_available: bool,
    ) -> dict[str, Any]:
        validation = [
            row
            for row in hits
            if row.signal_date in set(fold.validation_dates) and math.isfinite(row.realized_return_pct)
        ]
        books = {arm: _daily_book(validation, mode=arm) for arm in GATE_ARMS}
        if not fold.eligible:
            return _empty_gate_fold(fold, validation, abort_reason=fold.ineligible_reason)
        if len(books["ungated"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(fold, validation, abort_reason="Ungated validation book is too small.")
        if len(books["nfci_only"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(fold, validation, abort_reason="NFCI-gated validation book is too small.")
        if hy_available and len(books["hy_oas_only"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(
                fold,
                validation,
                abort_reason="HY OAS KEEP-gated validation book is too small.",
            )
        metrics = {arm: _book_metrics(books[arm]) for arm in GATE_ARMS}
        breadth_available = any(row.breadth_gate is not None for row in validation)
        breadth_book = _daily_book(validation, mode="hy_plus_nfci_breadth") if breadth_available else {}
        breadth_metrics = _book_metrics(breadth_book) if breadth_available and breadth_book else None
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_hits": len(validation),
            "n_days": {arm: len(books[arm]) for arm in GATE_ARMS},
            "ungated": metrics["ungated"],
            "hy_oas_only": metrics["hy_oas_only"] if hy_available else None,
            "nfci_only": metrics["nfci_only"],
            "hy_plus_nfci": metrics["hy_plus_nfci"] if hy_available else None,
            "hy_plus_nfci_breadth": breadth_metrics,
            "lift_nfci_vs_ungated": _metric_lift(metrics["nfci_only"], metrics["ungated"]),
            "lift_hy_vs_ungated": (
                _metric_lift(metrics["hy_oas_only"], metrics["ungated"]) if hy_available else None
            ),
            "lift_hy_plus_nfci_vs_hy": (
                _metric_lift(metrics["hy_plus_nfci"], metrics["hy_oas_only"]) if hy_available else None
            ),
            "lift_hy_plus_nfci_vs_ungated": (
                _metric_lift(metrics["hy_plus_nfci"], metrics["ungated"]) if hy_available else None
            ),
            "hy_keep_available": hy_available,
            "breadth_keep_shipped": breadth_available,
            "abort_reason": None,
        }

    def _evaluate_nested_fold(
        self,
        hits: Sequence[LongScreenObservation],
        fold: WalkForwardFoldSpec,
        *,
        hy_available: bool,
        breadth_available: bool,
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
        baseline_names = list(VOL_FEATURES)
        if breadth_available:
            baseline_names.extend(BREADTH_FEATURES)
        baseline_features = _usable_features(train_rows, baseline_names)
        hy_features = _usable_features(train_rows, HY_FEATURES) if hy_available else []
        nfci_features = _usable_features(train_rows, NFCI_FEATURES)
        if not baseline_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                abort_reason="Equity-vol (and breadth, if shipped) features are unavailable in training.",
            )
        if not nfci_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                abort_reason="NFCI features are unavailable in the training window.",
            )
        if hy_available and not hy_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                used_nfci_features=tuple(nfci_features),
                abort_reason="KEEP HY OAS features are unavailable in the training window.",
            )
        if len(validation_rows) < MIN_FOLD_HITS:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                used_hy_features=tuple(hy_features),
                used_nfci_features=tuple(nfci_features),
                abort_reason="Nested-model validation sample is too small.",
            )
        y_train = np.array([row.realized_return_pct for row in train_rows], dtype=float)
        realized = np.array([row.realized_return_pct for row in validation_rows], dtype=float)
        baseline_pred = _predict_ols(train_rows, validation_rows, baseline_features, y_train)
        nfci_pred = _predict_ols(
            train_rows,
            validation_rows,
            (*baseline_features, *nfci_features),
            y_train,
        )
        hy_pred = (
            _predict_ols(train_rows, validation_rows, (*baseline_features, *hy_features), y_train)
            if hy_features
            else None
        )
        both_pred = (
            _predict_ols(
                train_rows,
                validation_rows,
                (*baseline_features, *hy_features, *nfci_features),
                y_train,
            )
            if hy_features
            else None
        )
        baseline_metrics = _prediction_metrics(baseline_pred, realized)
        nfci_metrics = _prediction_metrics(nfci_pred, realized)
        hy_metrics = _prediction_metrics(hy_pred, realized) if hy_pred is not None else None
        both_metrics = _prediction_metrics(both_pred, realized) if both_pred is not None else None
        lift_nfci_vs_baseline = {
            key: _subtract(nfci_metrics[key], baseline_metrics[key])
            for key in ("spearman_ic", "r_squared")
        }
        lift_nfci_vs_hy = (
            {
                key: _subtract(both_metrics[key], hy_metrics[key])
                for key in ("spearman_ic", "r_squared")
            }
            if both_metrics is not None and hy_metrics is not None
            else {"spearman_ic": None, "r_squared": None}
        )
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_train": len(train_rows),
            "n_validation": len(validation_rows),
            "baseline": baseline_metrics,
            "hy_only": hy_metrics,
            "nfci_only": nfci_metrics,
            "hy_plus_nfci": both_metrics,
            "lift_nfci_vs_baseline": lift_nfci_vs_baseline,
            "lift_nfci_vs_hy": lift_nfci_vs_hy,
            "redundant_with_hy_oas": _is_redundant(lift_nfci_vs_hy) if hy_available else False,
            "used_baseline_features": list(baseline_features),
            "used_hy_features": list(hy_features),
            "used_nfci_features": list(nfci_features),
            "hy_keep_available": hy_available,
            "abort_reason": None,
        }

    def _verdict(
        self,
        gate_results: Sequence[Mapping[str, Any]],
        nested_results: Sequence[Mapping[str, Any]],
        abort_reasons: Sequence[str],
        *,
        hy_available: bool,
        breadth_available: bool,
    ) -> dict[str, Any]:
        eligible_gate = [row for row in gate_results if row.get("eligible")]
        eligible_nested = [row for row in nested_results if row.get("eligible")]
        gated_metric_lifts = {
            metric: sum(
                1
                for row in eligible_gate
                if (row.get("lift_hy_plus_nfci_vs_hy") or {}).get(metric) is not None
                and float(row["lift_hy_plus_nfci_vs_hy"][metric]) > 0
            )
            for metric in PRIMARY_METRICS
        }
        winning_gated_metrics = [metric for metric, wins in gated_metric_lifts.items() if wins >= 2]
        nested_ic_lifts = [
            float(row["lift_nfci_vs_hy"]["spearman_ic"])
            for row in eligible_nested
            if row.get("lift_nfci_vs_hy", {}).get("spearman_ic") is not None
        ]
        nested_r2_lifts = [
            float(row["lift_nfci_vs_hy"]["r_squared"])
            for row in eligible_nested
            if row.get("lift_nfci_vs_hy", {}).get("r_squared") is not None
        ]
        nested_positive_folds = sum(
            1
            for row in eligible_nested
            if _positive_incremental(row.get("lift_nfci_vs_hy") or {})
        )
        mean_nested_ic_lift = (
            round(sum(nested_ic_lifts) / len(nested_ic_lifts), 6) if nested_ic_lifts else None
        )
        mean_nested_r2_lift = (
            round(sum(nested_r2_lifts) / len(nested_r2_lifts), 6) if nested_r2_lifts else None
        )
        redundant = (
            hy_available
            and mean_nested_ic_lift is not None
            and mean_nested_r2_lift is not None
            and abs(mean_nested_ic_lift) < REDUNDANCY_IC_EPSILON
            and abs(mean_nested_r2_lift) < REDUNDANCY_R2_EPSILON
        )
        incremental_explanatory = nested_positive_folds >= 2
        reasons = list(abort_reasons)
        kill_switch = "not_triggered"
        if reasons:
            outcome = "aborted"
        elif not hy_available:
            outcome = "aborted"
            reasons.append(
                "KEEP HY OAS comparator is unavailable; the nested kill switch versus "
                "credit-gate-v1 cannot be scored."
            )
        elif len(eligible_gate) < 3:
            outcome = "aborted"
            reasons.append(
                f"Only {len(eligible_gate)} eligible gate folds were produced; 3 are required."
            )
        elif redundant and not winning_gated_metrics:
            outcome = "fail"
            kill_switch = "kill_redundant_with_hy_oas"
            reasons.append(
                "KILL: NFCI adds no incremental R² / IC versus KEEP HY OAS "
                f"(mean IC lift {mean_nested_ic_lift}, mean R² lift {mean_nested_r2_lift}) "
                "and HY+NFCI shows no gated lift versus HY OAS alone."
            )
        elif winning_gated_metrics or incremental_explanatory:
            outcome = "success"
            reasons.append(
                "NFCI added incremental gated performance and/or nested explanatory "
                "power versus KEEP HY OAS in at least 2 of 3 folds."
            )
        else:
            outcome = "fail"
            kill_switch = "kill_no_incremental_lift"
            reasons.append(
                "FAIL: NFCI did not improve HY+NFCI gated Sharpe/max drawdown versus "
                "HY OAS alone in at least 2 of 3 folds, and nested incremental IC/R² "
                "did not clear the redundancy band in at least 2 folds."
            )
        return {
            "outcome": outcome,
            "kill_switch": kill_switch,
            "eligible_gate_folds": len(eligible_gate),
            "eligible_nested_folds": len(eligible_nested),
            "positive_hy_plus_nfci_lift_folds_by_metric": gated_metric_lifts,
            "winning_primary_metrics": winning_gated_metrics,
            "nested_positive_incremental_folds": nested_positive_folds,
            "mean_nested_ic_lift_vs_hy": mean_nested_ic_lift,
            "mean_nested_r2_lift_vs_hy": mean_nested_r2_lift,
            "nfci_redundant_with_hy_oas": redundant,
            "hy_keep_available": hy_available,
            "breadth_keep_shipped": breadth_available,
            "abort_reasons": reasons,
            "live_surface_changed": False,
        }


def long_screen_from_row(row: Mapping[str, Any]) -> LongScreenObservation | None:
    realized = row.get("realized_return_pct")
    if realized is None:
        return None
    try:
        realized_return = float(realized)
        score = float(row.get("score"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(realized_return) or not math.isfinite(score):
        return None
    label = str(row.get("recommendation_label") or "")
    if score < MIN_LONG_TERM_SCAN_SCORE or label not in LONG_BIASED_LABELS:
        return None
    return LongScreenObservation(
        signal_id=str(row.get("signal_id") or ""),
        ticker=str(row.get("ticker") or "UNKNOWN").upper().strip(),
        signal_date=_parse_date(row.get("created_at")),
        realized_return_pct=realized_return,
        long_term_score=score,
        recommendation_label=label,
        strategy_family=str(row.get("strategy_family") or ""),
    )


def _daily_book(hits: Sequence[LongScreenObservation], *, mode: str) -> dict[date, float]:
    grouped: dict[date, list[LongScreenObservation]] = {}
    for hit in hits:
        grouped.setdefault(hit.signal_date, []).append(hit)
    book: dict[date, float] = {}
    for as_of, rows in grouped.items():
        mean_return = sum(row.realized_return_pct for row in rows) / len(rows)
        if mode == "ungated":
            book[as_of] = mean_return
            continue
        if mode == "hy_oas_only":
            weight = _gate_weight(rows[0].hy_gate, rows[0].hy_weight)
            if weight is None:
                continue
            book[as_of] = weight * mean_return
            continue
        if mode == "nfci_only":
            weight = _gate_weight(rows[0].nfci_gate, rows[0].nfci_weight)
            if weight is None:
                continue
            book[as_of] = weight * mean_return
            continue
        if mode == "hy_plus_nfci":
            hy_weight = _gate_weight(rows[0].hy_gate, rows[0].hy_weight)
            nfci_weight = _gate_weight(rows[0].nfci_gate, rows[0].nfci_weight)
            if hy_weight is None or nfci_weight is None:
                continue
            book[as_of] = hy_weight * nfci_weight * mean_return
            continue
        if mode == "hy_plus_nfci_breadth":
            if rows[0].breadth_gate != "open":
                continue
            hy_weight = _gate_weight(rows[0].hy_gate, rows[0].hy_weight)
            nfci_weight = _gate_weight(rows[0].nfci_gate, rows[0].nfci_weight)
            if hy_weight is None or nfci_weight is None:
                continue
            book[as_of] = hy_weight * nfci_weight * mean_return
            continue
        raise ValueError(f"Unknown book mode: {mode}")
    return book


def _gate_weight(status: GateStatus, stored: float | None) -> float | None:
    match status:
        case "unknown":
            return None
        case "full":
            return 1.0 if stored is None else float(stored)
        case "throttle":
            return THROTTLE_WEIGHT if stored is None else float(stored)
        case _ as unreachable:
            assert_never(unreachable)


def _book_metrics(book: Mapping[date, float]) -> dict[str, float | None]:
    if not book:
        return {"sharpe": None, "max_drawdown": None, "mean_return": None, "hit_rate": None, "n_days": 0}
    ordered = [book[key] for key in sorted(book)]
    arr = np.array(ordered, dtype=float)
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    sharpe = float(math.sqrt(252.0) * float(np.mean(arr)) / std) if std > 0 else None
    curve = np.cumprod(1.0 + arr / 100.0)
    peaks = np.maximum.accumulate(curve)
    drawdown = curve / peaks - 1.0
    max_dd = float(np.min(drawdown)) if len(drawdown) else None
    return {
        "sharpe": None if sharpe is None else round(sharpe, 6),
        "max_drawdown": None if max_dd is None else round(max_dd, 6),
        "mean_return": round(float(np.mean(arr)), 6),
        "hit_rate": round(float(np.mean(arr > 0)), 6),
        "n_days": int(len(arr)),
    }


def _metric_lift(
    gated: Mapping[str, float | None] | None,
    baseline: Mapping[str, float | None],
) -> dict[str, float | None]:
    if gated is None:
        return {"sharpe": None, "max_drawdown": None}
    return {metric: _subtract(gated.get(metric), baseline.get(metric)) for metric in PRIMARY_METRICS}


def _prediction_metrics(predicted: np.ndarray, realized: np.ndarray) -> dict[str, float | None]:
    return {
        "spearman_ic": _spearman_ic(predicted, realized),
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


def _r_squared(predicted: np.ndarray, realized: np.ndarray) -> float | None:
    if len(realized) < 3:
        return None
    residual = realized - predicted
    ss_res = float(np.sum(residual ** 2))
    ss_tot = float(np.sum((realized - np.mean(realized)) ** 2))
    if ss_tot <= 0:
        return None
    return round(1.0 - ss_res / ss_tot, 6)


def _usable_features(rows: Sequence[LongScreenObservation], names: Sequence[str]) -> list[str]:
    usable: list[str] = []
    if not rows:
        return usable
    for name in names:
        coverage = sum(row.feature_value(name) is not None for row in rows) / len(rows)
        if coverage >= MIN_FEATURE_COVERAGE:
            usable.append(name)
    return usable


def _predict_ols(
    train_rows: Sequence[LongScreenObservation],
    test_rows: Sequence[LongScreenObservation],
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


def _feature_matrix(rows: Sequence[LongScreenObservation], features: Sequence[str]) -> np.ndarray:
    return np.array([[row.feature_value(name) for name in features] for row in rows], dtype=float)


def _is_redundant(lift: Mapping[str, float | None]) -> bool:
    ic_lift = lift.get("spearman_ic")
    r2_lift = lift.get("r_squared")
    if ic_lift is None or r2_lift is None:
        return False
    return abs(float(ic_lift)) < REDUNDANCY_IC_EPSILON and abs(float(r2_lift)) < REDUNDANCY_R2_EPSILON


def _positive_incremental(lift: Mapping[str, float | None]) -> bool:
    ic_lift = lift.get("spearman_ic")
    r2_lift = lift.get("r_squared")
    ic_ok = ic_lift is not None and float(ic_lift) >= REDUNDANCY_IC_EPSILON
    r2_ok = r2_lift is not None and float(r2_lift) >= REDUNDANCY_R2_EPSILON
    return bool(ic_ok or r2_ok)


def _empty_gate_fold(
    fold: WalkForwardFoldSpec,
    validation: Sequence[LongScreenObservation],
    *,
    abort_reason: str | None,
) -> dict[str, Any]:
    empty = {"sharpe": None, "max_drawdown": None, "mean_return": None, "hit_rate": None, "n_days": 0}
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_hits": len(validation),
        "n_days": {arm: 0 for arm in GATE_ARMS},
        "ungated": empty,
        "hy_oas_only": None,
        "nfci_only": empty,
        "hy_plus_nfci": None,
        "hy_plus_nfci_breadth": None,
        "lift_nfci_vs_ungated": {"sharpe": None, "max_drawdown": None},
        "lift_hy_vs_ungated": None,
        "lift_hy_plus_nfci_vs_hy": None,
        "lift_hy_plus_nfci_vs_ungated": None,
        "hy_keep_available": False,
        "breadth_keep_shipped": False,
        "abort_reason": abort_reason,
    }


def _empty_nested_fold(
    fold: WalkForwardFoldSpec,
    train_rows: Sequence[LongScreenObservation],
    validation_rows: Sequence[LongScreenObservation],
    *,
    abort_reason: str | None,
    used_baseline_features: tuple[str, ...] = (),
    used_hy_features: tuple[str, ...] = (),
    used_nfci_features: tuple[str, ...] = (),
) -> dict[str, Any]:
    empty = {"spearman_ic": None, "r_squared": None, "n": 0}
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_train": len(train_rows),
        "n_validation": len(validation_rows),
        "baseline": empty,
        "hy_only": None,
        "nfci_only": empty,
        "hy_plus_nfci": None,
        "lift_nfci_vs_baseline": {"spearman_ic": None, "r_squared": None},
        "lift_nfci_vs_hy": {"spearman_ic": None, "r_squared": None},
        "redundant_with_hy_oas": False,
        "used_baseline_features": list(used_baseline_features),
        "used_hy_features": list(used_hy_features),
        "used_nfci_features": list(used_nfci_features),
        "hy_keep_available": False,
        "abort_reason": abort_reason,
    }


def _subtract(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 6)


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _split_dates(dates: Sequence[date], parts: int) -> list[list[date]]:
    if parts <= 0 or not dates:
        return []
    size = math.ceil(len(dates) / parts)
    return [list(dates[index : index + size]) for index in range(0, len(dates), size)][:parts]


__all__ = [
    "GATE_ARMS",
    "HY_FEATURES",
    "NESTED_ARMS",
    "NFCI_FEATURES",
    "PRIMARY_METRICS",
    "VOL_FEATURES",
    "LongScreenObservation",
    "NfciRegimeEvalService",
    "long_screen_from_row",
]
