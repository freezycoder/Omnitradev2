from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence
from typing import assert_never

import numpy as np
import pandas as pd

from application.calibration_research_service import WALK_FORWARD_EMBARGO_DAYS, WALK_FORWARD_FOLDS
from config.performance import MIN_LONG_TERM_SCAN_SCORE, PERFORMANCE_DB_FILE
from config.stfm_funding_liquidity import (
    ICE_REDISTRIBUTION_NOTICE,
    REDUNDANCY_IC_EPSILON,
    REDUNDANCY_R2_EPSILON,
    RORO_INGEST_V1,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    nfci_keep_recipe_manifest,
    stfm_recipe_manifest,
)
from config.thresholds import SCANNER_RULES
from domain.scoring.stfm_funding_liquidity import (
    GateStatus,
    HyKeepPanel,
    NfciKeepPanel,
    StfmPanel,
    build_hy_keep_panel,
    build_nfci_keep_panel,
    build_stfm_panel,
    build_stfm_regime_view,
)
from providers.macro.ofr_stfm_client import StfmSeriesBundle
from storage.repositories.outcome_repository import OutcomeRepository


PRIMARY_METRICS = ("sharpe", "max_drawdown")
VOL_FEATURES = ("spy_realized_vol_20d",)
HY_FEATURES = ("hy_oas", "hy_oas_d20_bp", "hy_oas_d5_bp", "hy_ig_gap")
NFCI_FEATURES = ("nfci_level", "nfci_d4w", "nfci_rising_streak")
SOFR_FEATURES = ("sofr_effr_spread_bp", "sofr_effr_d5_bp")
VOLUME_MMF_FEATURES = (
    "dvp_z",
    "gcf_z",
    "dvp_d5_pct",
    "dvp_d20_pct",
    "gcf_d5_pct",
    "gcf_d20_pct",
    "mmf_z",
    "mmf_d1m_pct",
)
STFM_FULL_FEATURES = (*SOFR_FEATURES, *VOLUME_MMF_FEATURES)
MIN_FOLD_DATES = 4
MIN_FOLD_HITS = 12
MIN_GATED_FOLD_DAYS = 4
MIN_FEATURE_COVERAGE = 0.50
LONG_BIASED_LABELS = SCANNER_RULES.long_term_labels
LONG_TERM_FAMILIES = ("long_term_3m", "long_term_6m", "long_term_12m")
GATE_ARMS = (
    "ungated",
    "hy_oas_only",
    "nfci_only",
    "hy_plus_nfci",
    "sofr_only",
    "stfm_full",
    "hy_nfci_plus_stfm",
)
NESTED_ARMS = (
    "baseline",
    "hy_plus_nfci",
    "sofr_only",
    "stfm_full",
    "hy_nfci_plus_stfm",
)


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
    dvp_z: float | None = None
    gcf_z: float | None = None
    dvp_d5_pct: float | None = None
    dvp_d20_pct: float | None = None
    gcf_d5_pct: float | None = None
    gcf_d20_pct: float | None = None
    mmf_z: float | None = None
    mmf_d1m_pct: float | None = None
    sofr_effr_spread_bp: float | None = None
    sofr_effr_d5_bp: float | None = None
    hy_gate: GateStatus = "unknown"
    hy_weight: float | None = None
    nfci_gate: GateStatus = "unknown"
    nfci_weight: float | None = None
    sofr_gate: GateStatus = "unknown"
    sofr_weight: float | None = None
    stfm_gate: GateStatus = "unknown"
    stfm_weight: float | None = None

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


class StfmFundingLiquidityEvalService:
    """Offline STFM nested-gate harness. Never writes live scores or recommendations."""

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
        stfm_panel: StfmPanel,
        hy_panel: HyKeepPanel,
        nfci_panel: NfciKeepPanel,
        hits: Sequence[LongScreenObservation] | None = None,
    ) -> dict[str, Any]:
        resolved_hits = self._with_panel_features(
            hits if hits is not None else self._load_hits(),
            stfm_panel,
            hy_panel,
            nfci_panel,
        )
        abort_reasons = list(stfm_panel.abort_reasons)
        abort_reasons.extend(hy_panel.abort_reasons)
        abort_reasons.extend(nfci_panel.abort_reasons)
        abort_reasons.extend(self._hit_abort_reasons(resolved_hits))
        hy_available = not hy_panel.abort_reasons and hy_panel.hy_count > 0
        nfci_available = not nfci_panel.abort_reasons and nfci_panel.nfci_count > 0
        keep_available = hy_available and nfci_available
        folds = self._build_folds(resolved_hits)
        comparators = [
            self._evaluate_gate_fold(
                resolved_hits,
                fold,
                hy_available=hy_available,
                nfci_available=nfci_available,
            )
            for fold in folds
        ]
        nested_results = [
            self._evaluate_nested_fold(
                resolved_hits,
                fold,
                hy_available=hy_available,
                nfci_available=nfci_available,
            )
            for fold in folds
        ]
        view = build_stfm_regime_view(stfm_panel)
        verdict = self._verdict(
            comparators,
            nested_results,
            abort_reasons,
            hy_available=hy_available,
            nfci_available=nfci_available,
        )
        return {
            "status": "research_only",
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_recommendation_changes": False,
                "live_ranking_changes": False,
                "is_stock_picker": False,
                "message": (
                    "OFR STFM is a shadow funding-liquidity regime overlay. This harness "
                    "never writes production scores or recommendations."
                ),
            },
            "pre_registration": {
                "recipe": stfm_recipe_manifest(),
                "hy_keep_comparator": hy_keep_recipe_manifest(),
                "nfci_keep_comparator": nfci_keep_recipe_manifest(),
                "roro_ingest_v1": RORO_INGEST_V1,
                "primary_metrics": list(PRIMARY_METRICS),
                "gate_arms": list(GATE_ARMS),
                "nested_arms": list(NESTED_ARMS),
                "success_rule": (
                    "Full STFM pack beats SOFR-only on Sharpe or max drawdown and adds "
                    "incremental gated lift or nested IC/R² versus HY+NFCI, each in at "
                    "least 2 of 3 walk-forward folds."
                ),
                "kill_switch": (
                    "KILL no-lift if STFM adds nothing versus HY+NFCI. KILL SOFR-only if "
                    "volumes+MMF sit inside the redundancy band versus SOFR-only and the "
                    "full pack shows no gated lift versus SOFR-only."
                ),
                "gate_is_fitted": False,
                "roro_invented": False,
            },
            "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
            "stfm_panel": stfm_panel.to_dict(),
            "hy_keep_panel": hy_panel.to_dict(),
            "nfci_keep_panel": nfci_panel.to_dict(),
            "latest_view": view.to_dict(),
            "data_quality": self._data_quality(
                resolved_hits,
                stfm_panel,
                hy_panel,
                nfci_panel,
            ),
            "abort_reasons": abort_reasons,
            "walk_forward_folds": [asdict(fold) for fold in folds],
            "gate_fold_results": comparators,
            "nested_fold_results": nested_results,
            "verdict": verdict,
            "keep_available": keep_available,
        }

    def evaluate_bundle(
        self,
        bundle: StfmSeriesBundle,
        *,
        spy_history: pd.DataFrame | None = None,
        hits: Sequence[LongScreenObservation] | None = None,
    ) -> dict[str, Any]:
        stfm_panel = build_stfm_panel(bundle, spy_history=spy_history)
        hy_panel = build_hy_keep_panel(bundle)
        nfci_panel = build_nfci_keep_panel(bundle)
        return self.evaluate_panels(
            stfm_panel,
            hy_panel,
            nfci_panel,
            hits=hits,
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
        stfm_panel: StfmPanel,
        hy_panel: HyKeepPanel,
        nfci_panel: NfciKeepPanel,
    ) -> list[LongScreenObservation]:
        joined: list[LongScreenObservation] = []
        for hit in hits:
            stfm_snapshot = stfm_panel.snapshot_on(hit.signal_date)
            hy_snapshot = hy_panel.snapshot_on(hit.signal_date)
            nfci_snapshot = nfci_panel.snapshot_on(hit.signal_date)
            joined.append(
                replace(
                    hit,
                    spy_realized_vol_20d=(
                        stfm_snapshot.spy_realized_vol_20d
                        if stfm_snapshot and stfm_snapshot.spy_realized_vol_20d is not None
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
                    dvp_z=stfm_snapshot.dvp_z if stfm_snapshot else hit.dvp_z,
                    gcf_z=stfm_snapshot.gcf_z if stfm_snapshot else hit.gcf_z,
                    dvp_d5_pct=stfm_snapshot.dvp_d5_pct if stfm_snapshot else hit.dvp_d5_pct,
                    dvp_d20_pct=stfm_snapshot.dvp_d20_pct if stfm_snapshot else hit.dvp_d20_pct,
                    gcf_d5_pct=stfm_snapshot.gcf_d5_pct if stfm_snapshot else hit.gcf_d5_pct,
                    gcf_d20_pct=stfm_snapshot.gcf_d20_pct if stfm_snapshot else hit.gcf_d20_pct,
                    mmf_z=stfm_snapshot.mmf_z if stfm_snapshot else hit.mmf_z,
                    mmf_d1m_pct=stfm_snapshot.mmf_d1m_pct if stfm_snapshot else hit.mmf_d1m_pct,
                    sofr_effr_spread_bp=(
                        stfm_snapshot.sofr_effr_spread_bp if stfm_snapshot else hit.sofr_effr_spread_bp
                    ),
                    sofr_effr_d5_bp=stfm_snapshot.sofr_effr_d5_bp if stfm_snapshot else hit.sofr_effr_d5_bp,
                    hy_gate=hy_snapshot.gate.status if hy_snapshot else "unknown",
                    hy_weight=hy_snapshot.gate.throttle_weight if hy_snapshot else None,
                    nfci_gate=nfci_snapshot.gate.status if nfci_snapshot else "unknown",
                    nfci_weight=nfci_snapshot.gate.throttle_weight if nfci_snapshot else None,
                    sofr_gate=stfm_snapshot.sofr_only_gate.status if stfm_snapshot else "unknown",
                    sofr_weight=(
                        stfm_snapshot.sofr_only_gate.throttle_weight if stfm_snapshot else None
                    ),
                    stfm_gate=stfm_snapshot.full_pack_gate.status if stfm_snapshot else "unknown",
                    stfm_weight=(
                        stfm_snapshot.full_pack_gate.throttle_weight if stfm_snapshot else None
                    ),
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
        stfm_panel: StfmPanel,
        hy_panel: HyKeepPanel,
        nfci_panel: NfciKeepPanel,
    ) -> dict[str, Any]:
        dates = sorted({row.signal_date for row in hits})
        return {
            "long_screen_hits": len(hits),
            "distinct_tickers": len({row.ticker for row in hits}),
            "distinct_signal_dates": len(dates),
            "period_start": dates[0].isoformat() if dates else None,
            "period_end": dates[-1].isoformat() if dates else None,
            "stfm_full_hits": sum(row.stfm_gate == "full" for row in hits),
            "stfm_throttle_hits": sum(row.stfm_gate == "throttle" for row in hits),
            "stfm_unknown_hits": sum(row.stfm_gate == "unknown" for row in hits),
            "sofr_throttle_hits": sum(row.sofr_gate == "throttle" for row in hits),
            "hy_keep_available": not hy_panel.abort_reasons and hy_panel.hy_count > 0,
            "nfci_keep_available": not nfci_panel.abort_reasons and nfci_panel.nfci_count > 0,
            "roro_ingest_v1": RORO_INGEST_V1,
            "stfm_history_days": len(stfm_panel.rows),
            "series_source": stfm_panel.source,
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
        nfci_available: bool,
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
        if len(books["stfm_full"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(fold, validation, abort_reason="STFM-gated validation book is too small.")
        if len(books["sofr_only"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(fold, validation, abort_reason="SOFR-only gated validation book is too small.")
        if hy_available and len(books["hy_oas_only"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(
                fold,
                validation,
                abort_reason="HY OAS KEEP-gated validation book is too small.",
            )
        if nfci_available and len(books["nfci_only"]) < MIN_GATED_FOLD_DAYS:
            return _empty_gate_fold(
                fold,
                validation,
                abort_reason="NFCI KEEP-gated validation book is too small.",
            )
        metrics = {arm: _book_metrics(books[arm]) for arm in GATE_ARMS}
        keep_available = hy_available and nfci_available
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_hits": len(validation),
            "n_days": {arm: len(books[arm]) for arm in GATE_ARMS},
            "ungated": metrics["ungated"],
            "hy_oas_only": metrics["hy_oas_only"] if hy_available else None,
            "nfci_only": metrics["nfci_only"] if nfci_available else None,
            "hy_plus_nfci": metrics["hy_plus_nfci"] if keep_available else None,
            "sofr_only": metrics["sofr_only"],
            "stfm_full": metrics["stfm_full"],
            "hy_nfci_plus_stfm": metrics["hy_nfci_plus_stfm"] if keep_available else None,
            "lift_stfm_vs_ungated": _metric_lift(metrics["stfm_full"], metrics["ungated"]),
            "lift_stfm_vs_sofr": _metric_lift(metrics["stfm_full"], metrics["sofr_only"]),
            "lift_stfm_vs_hy_nfci": (
                _metric_lift(metrics["hy_nfci_plus_stfm"], metrics["hy_plus_nfci"])
                if keep_available
                else None
            ),
            "hy_keep_available": hy_available,
            "nfci_keep_available": nfci_available,
            "roro_ingest_v1": RORO_INGEST_V1,
            "abort_reason": None,
        }

    def _evaluate_nested_fold(
        self,
        hits: Sequence[LongScreenObservation],
        fold: WalkForwardFoldSpec,
        *,
        hy_available: bool,
        nfci_available: bool,
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
        baseline_features = _usable_features(train_rows, VOL_FEATURES)
        sofr_features = _usable_features(train_rows, SOFR_FEATURES)
        volume_mmf_features = _usable_features(train_rows, VOLUME_MMF_FEATURES)
        stfm_features = _usable_features(train_rows, STFM_FULL_FEATURES)
        hy_features = _usable_features(train_rows, HY_FEATURES) if hy_available else []
        nfci_features = _usable_features(train_rows, NFCI_FEATURES) if nfci_available else []
        keep_features = [*hy_features, *nfci_features]
        if not baseline_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                abort_reason="Equity-vol features are unavailable in training.",
            )
        if not stfm_features:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                abort_reason="STFM features are unavailable in the training window.",
            )
        if len(validation_rows) < MIN_FOLD_HITS:
            return _empty_nested_fold(
                fold,
                train_rows,
                validation_rows,
                used_baseline_features=tuple(baseline_features),
                used_stfm_features=tuple(stfm_features),
                abort_reason="Nested-model validation sample is too small.",
            )
        y_train = np.array([row.realized_return_pct for row in train_rows], dtype=float)
        realized = np.array([row.realized_return_pct for row in validation_rows], dtype=float)
        baseline_pred = _predict_ols(train_rows, validation_rows, baseline_features, y_train)
        sofr_pred = (
            _predict_ols(train_rows, validation_rows, (*baseline_features, *sofr_features), y_train)
            if sofr_features
            else None
        )
        stfm_pred = _predict_ols(
            train_rows,
            validation_rows,
            (*baseline_features, *stfm_features),
            y_train,
        )
        keep_pred = (
            _predict_ols(train_rows, validation_rows, (*baseline_features, *keep_features), y_train)
            if keep_features
            else None
        )
        both_pred = (
            _predict_ols(
                train_rows,
                validation_rows,
                (*baseline_features, *keep_features, *stfm_features),
                y_train,
            )
            if keep_features
            else None
        )
        baseline_metrics = _prediction_metrics(baseline_pred, realized)
        sofr_metrics = _prediction_metrics(sofr_pred, realized) if sofr_pred is not None else None
        stfm_metrics = _prediction_metrics(stfm_pred, realized)
        keep_metrics = _prediction_metrics(keep_pred, realized) if keep_pred is not None else None
        both_metrics = _prediction_metrics(both_pred, realized) if both_pred is not None else None
        lift_stfm_vs_sofr = (
            {
                key: _subtract(stfm_metrics[key], sofr_metrics[key])
                for key in ("spearman_ic", "r_squared")
            }
            if sofr_metrics is not None
            else {"spearman_ic": None, "r_squared": None}
        )
        lift_stfm_vs_keep = (
            {
                key: _subtract(both_metrics[key], keep_metrics[key])
                for key in ("spearman_ic", "r_squared")
            }
            if both_metrics is not None and keep_metrics is not None
            else {"spearman_ic": None, "r_squared": None}
        )
        return {
            "fold": fold.fold,
            "eligible": True,
            "n_train": len(train_rows),
            "n_validation": len(validation_rows),
            "baseline": baseline_metrics,
            "hy_plus_nfci": keep_metrics,
            "sofr_only": sofr_metrics,
            "stfm_full": stfm_metrics,
            "hy_nfci_plus_stfm": both_metrics,
            "lift_stfm_vs_sofr": lift_stfm_vs_sofr,
            "lift_stfm_vs_hy_nfci": lift_stfm_vs_keep,
            "redundant_with_sofr_only": _is_redundant(lift_stfm_vs_sofr),
            "redundant_with_hy_nfci": _is_redundant(lift_stfm_vs_keep) if keep_features else False,
            "used_baseline_features": list(baseline_features),
            "used_sofr_features": list(sofr_features),
            "used_volume_mmf_features": list(volume_mmf_features),
            "used_stfm_features": list(stfm_features),
            "used_hy_features": list(hy_features),
            "used_nfci_features": list(nfci_features),
            "hy_keep_available": hy_available,
            "nfci_keep_available": nfci_available,
            "abort_reason": None,
        }

    def _verdict(
        self,
        gate_results: Sequence[Mapping[str, Any]],
        nested_results: Sequence[Mapping[str, Any]],
        abort_reasons: Sequence[str],
        *,
        hy_available: bool,
        nfci_available: bool,
    ) -> dict[str, Any]:
        eligible_gate = [row for row in gate_results if row.get("eligible")]
        eligible_nested = [row for row in nested_results if row.get("eligible")]
        keep_available = hy_available and nfci_available
        stfm_vs_sofr_lifts = {
            metric: sum(
                1
                for row in eligible_gate
                if (row.get("lift_stfm_vs_sofr") or {}).get(metric) is not None
                and float(row["lift_stfm_vs_sofr"][metric]) > 0
            )
            for metric in PRIMARY_METRICS
        }
        stfm_vs_keep_lifts = {
            metric: sum(
                1
                for row in eligible_gate
                if (row.get("lift_stfm_vs_hy_nfci") or {}).get(metric) is not None
                and float(row["lift_stfm_vs_hy_nfci"][metric]) > 0
            )
            for metric in PRIMARY_METRICS
        }
        beating_sofr = [metric for metric, wins in stfm_vs_sofr_lifts.items() if wins >= 2]
        beating_keep = [metric for metric, wins in stfm_vs_keep_lifts.items() if wins >= 2]
        nested_vs_sofr_positive = sum(
            1
            for row in eligible_nested
            if _positive_incremental(row.get("lift_stfm_vs_sofr") or {})
        )
        nested_vs_keep_positive = sum(
            1
            for row in eligible_nested
            if _positive_incremental(row.get("lift_stfm_vs_hy_nfci") or {})
        )
        mean_ic_vs_sofr = _mean_lift(eligible_nested, "lift_stfm_vs_sofr", "spearman_ic")
        mean_r2_vs_sofr = _mean_lift(eligible_nested, "lift_stfm_vs_sofr", "r_squared")
        mean_ic_vs_keep = _mean_lift(eligible_nested, "lift_stfm_vs_hy_nfci", "spearman_ic")
        mean_r2_vs_keep = _mean_lift(eligible_nested, "lift_stfm_vs_hy_nfci", "r_squared")
        redundant_sofr = (
            mean_ic_vs_sofr is not None
            and mean_r2_vs_sofr is not None
            and abs(mean_ic_vs_sofr) < REDUNDANCY_IC_EPSILON
            and abs(mean_r2_vs_sofr) < REDUNDANCY_R2_EPSILON
        )
        redundant_keep = (
            keep_available
            and mean_ic_vs_keep is not None
            and mean_r2_vs_keep is not None
            and abs(mean_ic_vs_keep) < REDUNDANCY_IC_EPSILON
            and abs(mean_r2_vs_keep) < REDUNDANCY_R2_EPSILON
        )
        reasons = list(abort_reasons)
        kill_switch = "not_triggered"
        if reasons:
            outcome = "aborted"
        elif not keep_available:
            outcome = "aborted"
            reasons.append(
                "KEEP HY OAS and/or NFCI comparator is unavailable; the nested kill "
                "switch versus HY+NFCI cannot be scored. RORO was not discovered."
            )
        elif len(eligible_gate) < 3:
            outcome = "aborted"
            reasons.append(
                f"Only {len(eligible_gate)} eligible gate folds were produced; 3 are required."
            )
        elif redundant_sofr and not beating_sofr:
            outcome = "fail"
            kill_switch = "kill_sofr_only"
            reasons.append(
                "KILL: volumes+MMF add no incremental R² / IC versus SOFR-only "
                f"(mean IC lift {mean_ic_vs_sofr}, mean R² lift {mean_r2_vs_sofr}) "
                "and the full pack shows no gated lift versus SOFR-only."
            )
        elif redundant_keep and not beating_keep:
            outcome = "fail"
            kill_switch = "kill_redundant_with_hy_nfci"
            reasons.append(
                "KILL: STFM adds no incremental R² / IC versus KEEP HY+NFCI "
                f"(mean IC lift {mean_ic_vs_keep}, mean R² lift {mean_r2_vs_keep}) "
                "and HY+NFCI+STFM shows no gated lift versus HY+NFCI."
            )
        elif beating_sofr and (beating_keep or nested_vs_keep_positive >= 2):
            outcome = "success"
            reasons.append(
                "Full STFM pack beat SOFR-only and added incremental gated or nested "
                "lift versus HY+NFCI in at least 2 of 3 folds."
            )
        else:
            outcome = "fail"
            kill_switch = "kill_no_incremental_lift"
            reasons.append(
                "FAIL: full STFM pack did not beat SOFR-only and add incremental lift "
                "versus HY+NFCI in at least 2 of 3 folds."
            )
        return {
            "outcome": outcome,
            "kill_switch": kill_switch,
            "eligible_gate_folds": len(eligible_gate),
            "eligible_nested_folds": len(eligible_nested),
            "positive_stfm_vs_sofr_folds_by_metric": stfm_vs_sofr_lifts,
            "positive_stfm_vs_hy_nfci_folds_by_metric": stfm_vs_keep_lifts,
            "winning_primary_metrics_vs_sofr": beating_sofr,
            "winning_primary_metrics_vs_hy_nfci": beating_keep,
            "nested_positive_vs_sofr_folds": nested_vs_sofr_positive,
            "nested_positive_vs_hy_nfci_folds": nested_vs_keep_positive,
            "mean_nested_ic_lift_vs_sofr": mean_ic_vs_sofr,
            "mean_nested_r2_lift_vs_sofr": mean_r2_vs_sofr,
            "mean_nested_ic_lift_vs_hy_nfci": mean_ic_vs_keep,
            "mean_nested_r2_lift_vs_hy_nfci": mean_r2_vs_keep,
            "volumes_mmf_redundant_with_sofr": redundant_sofr,
            "stfm_redundant_with_hy_nfci": redundant_keep,
            "hy_keep_available": hy_available,
            "nfci_keep_available": nfci_available,
            "roro_ingest_v1": RORO_INGEST_V1,
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
    family = str(row.get("strategy_family") or "")
    if family not in LONG_TERM_FAMILIES:
        return None
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
        sample = rows[0]
        if mode == "ungated":
            book[as_of] = mean_return
            continue
        if mode == "hy_oas_only":
            weight = _gate_weight(sample.hy_gate, sample.hy_weight)
        elif mode == "nfci_only":
            weight = _gate_weight(sample.nfci_gate, sample.nfci_weight)
        elif mode == "hy_plus_nfci":
            hy_weight = _gate_weight(sample.hy_gate, sample.hy_weight)
            nfci_weight = _gate_weight(sample.nfci_gate, sample.nfci_weight)
            weight = None if hy_weight is None or nfci_weight is None else hy_weight * nfci_weight
        elif mode == "sofr_only":
            weight = _gate_weight(sample.sofr_gate, sample.sofr_weight)
        elif mode == "stfm_full":
            weight = _gate_weight(sample.stfm_gate, sample.stfm_weight)
        elif mode == "hy_nfci_plus_stfm":
            hy_weight = _gate_weight(sample.hy_gate, sample.hy_weight)
            nfci_weight = _gate_weight(sample.nfci_gate, sample.nfci_weight)
            stfm_weight = _gate_weight(sample.stfm_gate, sample.stfm_weight)
            if hy_weight is None or nfci_weight is None or stfm_weight is None:
                weight = None
            else:
                weight = hy_weight * nfci_weight * stfm_weight
        else:
            raise ValueError(f"Unknown book mode: {mode}")
        if weight is None:
            continue
        book[as_of] = weight * mean_return
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


def _mean_lift(
    rows: Sequence[Mapping[str, Any]],
    field_name: str,
    metric: str,
) -> float | None:
    values = [
        float(row[field_name][metric])
        for row in rows
        if row.get(field_name, {}).get(metric) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


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
        "nfci_only": None,
        "hy_plus_nfci": None,
        "sofr_only": empty,
        "stfm_full": empty,
        "hy_nfci_plus_stfm": None,
        "lift_stfm_vs_ungated": {"sharpe": None, "max_drawdown": None},
        "lift_stfm_vs_sofr": {"sharpe": None, "max_drawdown": None},
        "lift_stfm_vs_hy_nfci": None,
        "hy_keep_available": False,
        "nfci_keep_available": False,
        "roro_ingest_v1": RORO_INGEST_V1,
        "abort_reason": abort_reason,
    }


def _empty_nested_fold(
    fold: WalkForwardFoldSpec,
    train_rows: Sequence[LongScreenObservation],
    validation_rows: Sequence[LongScreenObservation],
    *,
    abort_reason: str | None,
    used_baseline_features: tuple[str, ...] = (),
    used_stfm_features: tuple[str, ...] = (),
) -> dict[str, Any]:
    empty = {"spearman_ic": None, "r_squared": None, "n": 0}
    return {
        "fold": fold.fold,
        "eligible": False,
        "n_train": len(train_rows),
        "n_validation": len(validation_rows),
        "baseline": empty,
        "hy_plus_nfci": None,
        "sofr_only": None,
        "stfm_full": empty,
        "hy_nfci_plus_stfm": None,
        "lift_stfm_vs_sofr": {"spearman_ic": None, "r_squared": None},
        "lift_stfm_vs_hy_nfci": {"spearman_ic": None, "r_squared": None},
        "redundant_with_sofr_only": False,
        "redundant_with_hy_nfci": False,
        "used_baseline_features": list(used_baseline_features),
        "used_stfm_features": list(used_stfm_features),
        "hy_keep_available": False,
        "nfci_keep_available": False,
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
    "NESTED_ARMS",
    "PRIMARY_METRICS",
    "SOFR_FEATURES",
    "STFM_FULL_FEATURES",
    "VOLUME_MMF_FEATURES",
    "LongScreenObservation",
    "StfmFundingLiquidityEvalService",
    "long_screen_from_row",
]
