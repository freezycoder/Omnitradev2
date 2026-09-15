from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from application.calibration_research_service import WALK_FORWARD_EMBARGO_DAYS, WALK_FORWARD_FOLDS
from config.credit_regime import (
    ICE_REDISTRIBUTION_NOTICE,
    REDUNDANCY_IC_EPSILON,
    REDUNDANCY_R2_EPSILON,
    THROTTLE_WEIGHT,
    credit_recipe_manifest,
)
from config.performance import MIN_LONG_TERM_SCAN_SCORE, PERFORMANCE_DB_FILE
from config.thresholds import SCANNER_RULES
from domain.scoring.credit_regime import (
    CreditPanel,
    GateStatus,
    build_credit_panel,
    build_credit_regime_view,
    crisis_descriptive_overlay,
    lead_lag_diagnostics,
)
from providers.macro.credit_oas_client import CreditSeriesBundle
from storage.repositories.outcome_repository import OutcomeRepository


PRIMARY_METRICS = ("sharpe", "max_drawdown")
VOL_FEATURES = ("spy_realized_vol_20d",)
CREDIT_FEATURES = ("hy_oas", "hy_oas_d20_bp", "hy_oas_d5_bp", "hy_ig_gap")
BREADTH_FEATURES = ("pct_above_50dma",)
MIN_FOLD_DATES = 4
MIN_FOLD_HITS = 12
MIN_GATED_FOLD_DAYS = 4
MIN_FEATURE_COVERAGE = 0.50
LONG_BIASED_LABELS = SCANNER_RULES.long_term_labels


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
    pct_above_50dma: float | None = None
    credit_gate: GateStatus = "unknown"
    credit_weight: float | None = None
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


class CreditRegimeEvalService:
    """Offline credit-gate harness. Never writes live scores or recommendations."""

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

    def evaluate_panel(
        self,
        panel: CreditPanel,
        hits: Sequence[LongScreenObservation] | None = None,
        *,
        breadth_status_by_date: Mapping[date, str] | None = None,
    ) -> dict[str, Any]:
        resolved_hits = self._with_panel_features(
            hits if hits is not None else self._load_hits(),
            panel,
            breadth_status_by_date=breadth_status_by_date,
        )
        abort_reasons = list(panel.abort_reasons)
        abort_reasons.extend(self._hit_abort_reasons(resolved_hits))
        folds = self._build_folds(resolved_hits)
        comparators = [self._evaluate_gate_fold(resolved_hits, fold) for fold in folds]
        nested_results = [
            self._evaluate_nested_fold(resolved_hits, fold, breadth_available=breadth_status_by_date is not None)
            for fold in folds
        ]
        view = build_credit_regime_view(panel)
        verdict = self._verdict(
            comparators,
            nested_results,
            abort_reasons,
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
                    "HY OAS is a shadow credit regime gate that throttles long-screen "
                    "aggressiveness. This harness never writes production scores or recommendations."
                ),
            },
            "pre_registration": {
                "recipe": credit_recipe_manifest(),
                "primary_metrics": list(PRIMARY_METRICS),
                "comparators": ["ungated", "credit_gated", "breadth_gated", "both"],
                "success_rule": (
                    "The frozen credit throttle improves Sharpe or max drawdown of the "
                    "long-screen book versus ungated in at least 2 of 3 walk-forward folds, "
                    "and nested credit features are not redundant with equity vol "
                    "(or breadth + vol when KEEP breadth is available)."
                ),
                "gate_is_fitted": False,
                "sensitivity_is_appendix_only": True,
                "march_2020_is_tune_target": False,
            },
            "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
            "panel": panel.to_dict(),
            "latest_view": view.to_dict(),
            "lead_lag": lead_lag_diagnostics(panel),
            "crisis_descriptive": crisis_descriptive_overlay(panel),
            "data_quality": self._data_quality(resolved_hits, panel, breadth_status_by_date),
            "abort_reasons": abort_reasons,
            "walk_forward_folds": [asdict(fold) for fold in folds],
            "gate_fold_results": comparators,
            "nested_fold_results": nested_results,
            "verdict": verdict,
        }

    def evaluate_bundle(
        self,
        bundle: CreditSeriesBundle,
        *,
        spy_history: pd.DataFrame | None = None,
        hits: Sequence[LongScreenObservation] | None = None,
        breadth_status_by_date: Mapping[date, str] | None = None,
    ) -> dict[str, Any]:
        panel = build_credit_panel(bundle, spy_history=spy_history)
        return self.evaluate_panel(
            panel,
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
        panel: CreditPanel,
        *,
        breadth_status_by_date: Mapping[date, str] | None,
    ) -> list[LongScreenObservation]:
        joined: list[LongScreenObservation] = []
        for hit in hits:
            snapshot = panel.snapshot_on(hit.signal_date)
            credit_gate: GateStatus = snapshot.gate.status if snapshot else "unknown"
            credit_weight = snapshot.gate.throttle_weight if snapshot else None
            breadth_gate = None
            if breadth_status_by_date is not None:
                breadth_gate = breadth_status_by_date.get(hit.signal_date, "unknown")
            joined.append(
                replace(
                    hit,
                    spy_realized_vol_20d=snapshot.spy_realized_vol_20d if snapshot else hit.spy_realized_vol_20d,
                    hy_oas=snapshot.hy_oas if snapshot else hit.hy_oas,
                    hy_oas_d20_bp=snapshot.hy_oas_d20_bp if snapshot else hit.hy_oas_d20_bp,
                    hy_oas_d5_bp=snapshot.hy_oas_d5_bp if snapshot else hit.hy_oas_d5_bp,
                    hy_ig_gap=snapshot.hy_ig_gap if snapshot else hit.hy_ig_gap,
                    credit_gate=credit_gate,
                    credit_weight=credit_weight,
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
        panel: CreditPanel,
        breadth_status_by_date: Mapping[date, str] | None,
    ) -> dict[str, Any]:
        dates = sorted({row.signal_date for row in hits})
        return {
            "long_screen_hits": len(hits),
            "distinct_tickers": len({row.ticker for row in hits}),
            "distinct_signal_dates": len(dates),
            "period_start": dates[0].isoformat() if dates else None,
            "period_end": dates[-1].isoformat() if dates else None,
            "credit_full_hits": sum(row.credit_gate == "full" for row in hits),
            "credit_throttle_hits": sum(row.credit_gate == "throttle" for row in hits),
            "credit_unknown_hits": sum(row.credit_gate == "unknown" for row in hits),
            "breadth_keep_shipped": breadth_status_by_date is not None,
            "history_sessions": panel.history_sessions,
            "series_source": panel.source,
            "hy_count": panel.hy_count,
            "ig_count": panel.ig_count,
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
    ) -> dict[str, Any]:
        validation = [
            row
            for row in hits
            if row.signal_date in set(fold.validation_dates) and math.isfinite(row.realized_return_pct)
        ]
        ungated_book = _daily_book(validation, mode="ungated")
        credit_book = _daily_book(validation, mode="credit")
        breadth_book = _daily_book(validation, mode="breadth")
        both_book = _daily_book(validation, mode="both")
        if not fold.eligible:
            return _empty_gate_fold(fold, validation, abort_reason=fold.ineligible_reason)
        if len(ungated_book) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(
                fold,
                validation,
                abort_reason="Ungated validation book is too small.",
            )
        if len(credit_book) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(
                fold,
                validation,
                abort_reason="Credit-gated validation book is too small.",
            )
        ungated_metrics = _book_metrics(ungated_book)
        credit_metrics = _book_metrics(credit_book)
        breadth_available = any(row.breadth_gate is not None for row in validation)
        breadth_metrics = _book_metrics(breadth_book) if breadth_available and breadth_book else None
        both_metrics = _book_metrics(both_book) if breadth_available and both_book else None
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_hits": len(validation),
            "n_ungated_days": len(ungated_book),
            "n_credit_days": len(credit_book),
            "n_breadth_days": len(breadth_book) if breadth_available else None,
            "n_both_days": len(both_book) if breadth_available else None,
            "ungated": ungated_metrics,
            "credit_gated": credit_metrics,
            "breadth_gated": breadth_metrics,
            "both": both_metrics,
            "lift_credit_vs_ungated": _metric_lift(credit_metrics, ungated_metrics),
            "lift_breadth_vs_ungated": (
                _metric_lift(breadth_metrics, ungated_metrics) if breadth_metrics else None
            ),
            "lift_both_vs_ungated": _metric_lift(both_metrics, ungated_metrics) if both_metrics else None,
            "breadth_keep_shipped": breadth_available,
            "abort_reason": None,
        }

    def _evaluate_nested_fold(
        self,
        hits: Sequence[LongScreenObservation],
        fold: WalkForwardFoldSpec,
        *,
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
        credit_features = _usable_features(train_rows, CREDIT_FEATURES)
        if not baseline_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                abort_reason="Equity-vol (and breadth, if shipped) features are unavailable in training.",
            )
        if not credit_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                abort_reason="Credit OAS features are unavailable in the training window.",
            )
        if len(validation_rows) < MIN_FOLD_HITS:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                used_credit_features=tuple(credit_features),
                abort_reason="Nested-model validation sample is too small.",
            )
        y_train = np.array([row.realized_return_pct for row in train_rows], dtype=float)
        baseline_pred = _predict_ols(train_rows, validation_rows, baseline_features, y_train)
        nested_pred = _predict_ols(
            train_rows,
            validation_rows,
            (*baseline_features, *credit_features),
            y_train,
        )
        realized = np.array([row.realized_return_pct for row in validation_rows], dtype=float)
        baseline_metrics = _prediction_metrics(baseline_pred, realized)
        nested_metrics = _prediction_metrics(nested_pred, realized)
        lift = {
            key: _subtract(nested_metrics[key], baseline_metrics[key])
            for key in ("spearman_ic", "r_squared")
        }
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_train": len(train_rows),
            "n_validation": len(validation_rows),
            "baseline": baseline_metrics,
            "nested": nested_metrics,
            "lift": lift,
            "redundant": _is_redundant(lift),
            "used_baseline_features": list(baseline_features),
            "used_credit_features": list(credit_features),
            "abort_reason": None,
        }

    def _verdict(
        self,
        gate_results: Sequence[Mapping[str, Any]],
        nested_results: Sequence[Mapping[str, Any]],
        abort_reasons: Sequence[str],
        *,
        breadth_available: bool,
    ) -> dict[str, Any]:
        eligible_gate = [row for row in gate_results if row.get("eligible")]
        eligible_nested = [row for row in nested_results if row.get("eligible")]
        metric_lifts = {
            metric: sum(
                1
                for row in eligible_gate
                if row.get("lift_credit_vs_ungated", {}).get(metric) is not None
                and float(row["lift_credit_vs_ungated"][metric]) > 0
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
            control = "breadth + equity vol" if breadth_available else "equity vol"
            reasons.append(
                f"Nested credit features are redundant with {control} "
                f"(mean IC lift {mean_nested_ic_lift}, mean R² lift {mean_nested_r2_lift})."
            )
        elif winning_metrics:
            outcome = "success"
        else:
            outcome = "fail"
            reasons.append(
                "The frozen credit throttle did not improve Sharpe or max drawdown in at least 2 of 3 folds."
            )
        return {
            "outcome": outcome,
            "eligible_gate_folds": len(eligible_gate),
            "eligible_nested_folds": len(eligible_nested),
            "positive_credit_lift_folds_by_metric": metric_lifts,
            "winning_primary_metrics": winning_metrics,
            "mean_nested_ic_lift": mean_nested_ic_lift,
            "mean_nested_r2_lift": mean_nested_r2_lift,
            "credit_redundant_with_vol_or_breadth": redundant,
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


def _daily_book(
    hits: Sequence[LongScreenObservation],
    *,
    mode: str,
) -> dict[date, float]:
    grouped: dict[date, list[LongScreenObservation]] = {}
    for hit in hits:
        grouped.setdefault(hit.signal_date, []).append(hit)
    book: dict[date, float] = {}
    for as_of, rows in grouped.items():
        mean_return = sum(row.realized_return_pct for row in rows) / len(rows)
        if mode == "ungated":
            book[as_of] = mean_return
            continue
        if mode == "credit":
            gate = rows[0].credit_gate
            if gate == "unknown":
                continue
            weight = 1.0 if gate == "full" else THROTTLE_WEIGHT
            book[as_of] = weight * mean_return
            continue
        breadth = rows[0].breadth_gate
        if mode == "breadth":
            if breadth != "open":
                continue
            book[as_of] = mean_return
            continue
        if mode == "both":
            if breadth != "open" or rows[0].credit_gate == "unknown":
                continue
            weight = 1.0 if rows[0].credit_gate == "full" else THROTTLE_WEIGHT
            book[as_of] = weight * mean_return
    return book


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
    ungated: Mapping[str, float | None],
) -> dict[str, float | None]:
    if gated is None:
        return {"sharpe": None, "max_drawdown": None}
    return {
        metric: _subtract(gated.get(metric), ungated.get(metric))
        for metric in PRIMARY_METRICS
    }


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
        "n_ungated_days": 0,
        "n_credit_days": 0,
        "n_breadth_days": None,
        "n_both_days": None,
        "ungated": empty,
        "credit_gated": empty,
        "breadth_gated": None,
        "both": None,
        "lift_credit_vs_ungated": {"sharpe": None, "max_drawdown": None},
        "lift_breadth_vs_ungated": None,
        "lift_both_vs_ungated": None,
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
    used_credit_features: tuple[str, ...] = (),
) -> dict[str, Any]:
    empty = {"spearman_ic": None, "r_squared": None, "n": 0}
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_train": len(train_rows),
        "n_validation": len(validation_rows),
        "baseline": empty,
        "nested": empty,
        "lift": {"spearman_ic": None, "r_squared": None},
        "redundant": False,
        "used_baseline_features": list(used_baseline_features),
        "used_credit_features": list(used_credit_features),
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
    "CREDIT_FEATURES",
    "PRIMARY_METRICS",
    "VOL_FEATURES",
    "CreditRegimeEvalService",
    "LongScreenObservation",
    "long_screen_from_row",
]
