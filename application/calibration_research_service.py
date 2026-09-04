from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Iterable, Mapping, Sequence

from config.performance import MIN_EXECUTION_SCORE, PERFORMANCE_DB_FILE
from storage.repositories.outcome_repository import OutcomeRepository


SCORE_THRESHOLDS = (55, 60, 65, 70, 75, 80, 85)
COST_SCENARIOS_BPS = (5, 10, 20)
DEFAULT_COST_SCENARIO_BPS = 10
WALK_FORWARD_EMBARGO_DAYS = 15
WALK_FORWARD_FOLDS = 3
BOOTSTRAP_CONFIDENCE_LEVEL = 0.80
BOOTSTRAP_ITERATIONS = 300
CONFIDENCE_ORDER = {"Low": 0, "Balanced": 1, "Moderate": 2, "High": 3, "Very High": 4}
STRATEGY_LABELS = {
    "short_term_day": "1–2 Day Trades",
    "short_term_swing": "5–15 Day Swings",
}
REGIME_LABELS = {
    "ALL": "All Regimes",
    "MOMENTUM": "Momentum",
    "MEAN_REVERSION": "Mean Reversion",
    "UNKNOWN": "Unknown",
}


@dataclass(frozen=True)
class CalibrationObservation:
    signal_id: str
    ticker: str
    strategy_family: str
    score: float
    recommendation_label: str
    confidence_band: str
    regime: str
    source_quality: str
    signal_date: date
    evaluated_date: date
    realized_return_pct: float

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CalibrationObservation":
        score = float(row["score"])
        realized_return_pct = float(row["realized_return_pct"])
        if not math.isfinite(score) or not math.isfinite(realized_return_pct):
            raise ValueError("Calibration observations require finite score and return values.")
        return cls(
            signal_id=str(row["signal_id"]),
            ticker=str(row["ticker"] or "UNKNOWN").upper().strip(),
            strategy_family=str(row["strategy_family"]),
            score=score,
            recommendation_label=str(row["recommendation_label"] or "Unknown"),
            confidence_band=str(row["recommendation_confidence"] or "Unknown"),
            regime=_regime_from_row(row),
            source_quality=str(row["source_quality"] or "unknown"),
            signal_date=_parse_date(row["created_at"]),
            evaluated_date=_parse_date(row["evaluated_at"]),
            realized_return_pct=realized_return_pct,
        )


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    training_end: date
    validation_start: date
    validation_end: date
    validation_dates: tuple[date, ...]
    training_observations: int
    training_signal_dates: int
    validation_observations: int
    validation_signal_dates: int
    eligible: bool


class CalibrationResearchService:
    """Builds a deterministic research view without changing live configuration."""

    def __init__(
        self,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Path | None = None,
        *,
        observations: Sequence[CalibrationObservation] | None = None,
        bootstrap_iterations: int = BOOTSTRAP_ITERATIONS,
        bootstrap_seed: int = 20260725,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._provided_observations = tuple(observations) if observations is not None else None
        self._bootstrap_iterations = max(int(bootstrap_iterations), 40)
        self._bootstrap_seed = int(bootstrap_seed)

    def build_payload(self) -> dict[str, Any]:
        observations, invalid_rows_skipped = self._load_observations()
        folds = self._build_walk_forward_folds(observations)
        valid_validation_dates = {
            signal_date
            for fold in folds
            if fold.eligible
            for signal_date in fold.validation_dates
        }
        sensitivity = self._build_threshold_sensitivity(
            observations,
            folds=folds,
            valid_validation_dates=valid_validation_dates,
        )
        return {
            "status": "research_only",
            "deployment_guard": {
                "automatic_config_changes": False,
                "message": (
                    "Candidates are evidence for shadow testing only. "
                    "This analysis never writes production score thresholds."
                ),
            },
            "methodology": {
                "score_thresholds": list(SCORE_THRESHOLDS),
                "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
                "default_cost_scenario_bps": DEFAULT_COST_SCENARIO_BPS,
                "current_execution_threshold": MIN_EXECUTION_SCORE,
                "walk_forward": {
                    "requested_folds": WALK_FORWARD_FOLDS,
                    "eligible_folds": sum(1 for fold in folds if fold.eligible),
                    "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
                    "split_basis": "signal_created_date",
                    "design": "expanding_window_with_calendar_embargo",
                },
                "uncertainty": {
                    "method": "hierarchical_cluster_bootstrap",
                    "cluster_order": ["signal_date", "ticker"],
                    "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
                    "iterations": self._bootstrap_iterations,
                    "seed": self._bootstrap_seed,
                },
                "evidence_rules": {
                    "insufficient": "Fewer than 30 OOS signals or 8 OOS signal dates.",
                    "developing": "At least 30 OOS signals and 8 OOS signal dates.",
                    "established": "At least 50 OOS signals and 12 OOS signal dates.",
                },
            },
            "data_quality": self._build_data_quality(
                observations,
                folds,
                invalid_rows_skipped=invalid_rows_skipped,
            ),
            "walk_forward_folds": [self._fold_payload(fold) for fold in folds],
            "threshold_sensitivity": sensitivity,
            "current_vs_candidate": self._build_candidate_comparisons(sensitivity),
            "confidence_reliability": self._build_confidence_reliability(
                observations,
                valid_validation_dates=valid_validation_dates,
                has_eligible_folds=bool(valid_validation_dates),
            ),
        }

    def _load_observations(self) -> tuple[list[CalibrationObservation], int]:
        if self._provided_observations is not None:
            return (
                sorted(
                    self._provided_observations,
                    key=lambda row: (row.signal_date, row.ticker, row.signal_id),
                ),
                0,
            )
        self._outcome_repository.ensure_schema()
        observations: list[CalibrationObservation] = []
        invalid_rows_skipped = 0
        for row in self._outcome_repository.list_calibration_observations():
            try:
                observations.append(CalibrationObservation.from_row(row))
            except (TypeError, ValueError, OverflowError):
                invalid_rows_skipped += 1
        return observations, invalid_rows_skipped

    def _build_data_quality(
        self,
        observations: Sequence[CalibrationObservation],
        folds: Sequence[WalkForwardFold],
        *,
        invalid_rows_skipped: int,
    ) -> dict[str, Any]:
        date_counts = Counter(row.signal_date for row in observations)
        source_counts = Counter(row.source_quality for row in observations)
        regime_counts = Counter(row.regime for row in observations)
        largest_cluster = max(date_counts.values(), default=0)
        resolved = len(observations)
        distinct_dates = len(date_counts)
        distinct_tickers = len({row.ticker for row in observations})
        warnings: list[str] = []
        if resolved == 0:
            warnings.append("No resolved short-term outcomes are available.")
        if distinct_dates < 30:
            warnings.append(
                f"Only {distinct_dates} distinct signal dates are available; time diversity is still limited."
            )
        if distinct_tickers < 50:
            warnings.append(
                f"Only {distinct_tickers} distinct tickers are represented; cross-sectional coverage is limited."
            )
        if resolved and largest_cluster / resolved >= 0.20:
            warnings.append(
                "One signal date contains at least 20% of outcomes; naive row-level confidence would be overstated."
            )
        if not any(fold.eligible for fold in folds):
            warnings.append(
                "No walk-forward fold has enough pre-embargo training history; results fall back to in-sample diagnostics."
            )
        if regime_counts.get("UNKNOWN", 0):
            warnings.append(
                f"{regime_counts['UNKNOWN']} outcomes have no identifiable regime and are excluded from regime-specific candidates."
            )
        if invalid_rows_skipped:
            warnings.append(
                f"{invalid_rows_skipped} malformed outcome rows were excluded from calibration."
            )
        return {
            "resolved_signals": resolved,
            "invalid_rows_skipped": invalid_rows_skipped,
            "distinct_tickers": distinct_tickers,
            "distinct_signal_dates": distinct_dates,
            "period_start": min(date_counts).isoformat() if date_counts else None,
            "period_end": max(date_counts).isoformat() if date_counts else None,
            "largest_signal_date_cluster": largest_cluster,
            "largest_signal_date_share_pct": (
                round(largest_cluster / resolved * 100, 1) if resolved else None
            ),
            "source_quality_counts": dict(sorted(source_counts.items())),
            "regime_counts": dict(sorted(regime_counts.items())),
            "warnings": warnings,
        }

    def _build_walk_forward_folds(
        self,
        observations: Sequence[CalibrationObservation],
    ) -> list[WalkForwardFold]:
        unique_dates = sorted({row.signal_date for row in observations})
        if len(unique_dates) < 8:
            return []
        initial_training_dates = max(4, math.ceil(len(unique_dates) * 0.40))
        validation_pool = unique_dates[initial_training_dates:]
        blocks = _split_dates(validation_pool, min(WALK_FORWARD_FOLDS, len(validation_pool)))
        folds: list[WalkForwardFold] = []
        for index, validation_dates in enumerate(blocks, start=1):
            validation_start = validation_dates[0]
            training_end = validation_start - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)
            training_rows = [row for row in observations if row.signal_date <= training_end]
            validation_rows = [
                row for row in observations if row.signal_date in set(validation_dates)
            ]
            training_date_count = len({row.signal_date for row in training_rows})
            eligible = len(training_rows) >= 20 and training_date_count >= 4
            folds.append(
                WalkForwardFold(
                    fold=index,
                    training_end=training_end,
                    validation_start=validation_start,
                    validation_end=validation_dates[-1],
                    validation_dates=tuple(validation_dates),
                    training_observations=len(training_rows),
                    training_signal_dates=training_date_count,
                    validation_observations=len(validation_rows),
                    validation_signal_dates=len(validation_dates),
                    eligible=eligible,
                )
            )
        return folds

    def _build_threshold_sensitivity(
        self,
        observations: Sequence[CalibrationObservation],
        *,
        folds: Sequence[WalkForwardFold],
        valid_validation_dates: set[date],
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        segment_number = 0
        for strategy_family in STRATEGY_LABELS:
            for regime in ("ALL", "MOMENTUM", "MEAN_REVERSION"):
                segment = [
                    row
                    for row in observations
                    if row.strategy_family == strategy_family
                    and (regime == "ALL" or row.regime == regime)
                ]
                for threshold in SCORE_THRESHOLDS:
                    scoped = [row for row in segment if row.score >= threshold]
                    oos = [
                        row for row in scoped if row.signal_date in valid_validation_dates
                    ]
                    evaluation_rows = oos if valid_validation_dates else scoped
                    interval = self._cluster_bootstrap_interval(
                        evaluation_rows,
                        value=lambda row: row.realized_return_pct,
                        seed_offset=segment_number * 100,
                    )
                    evidence_level = self._evidence_level(evaluation_rows)
                    fold_expectancies = self._fold_expectancies(
                        scoped,
                        folds=folds,
                        cost_bps=DEFAULT_COST_SCENARIO_BPS,
                    )
                    for cost_bps in COST_SCENARIOS_BPS:
                        cost_pct = cost_bps / 100
                        gross = _mean_return(scoped)
                        oos_gross = _mean_return(evaluation_rows)
                        low = interval[0] - cost_pct if interval else None
                        high = interval[1] - cost_pct if interval else None
                        net = gross - cost_pct if gross is not None else None
                        oos_net = oos_gross - cost_pct if oos_gross is not None else None
                        row = {
                            "strategy_family": strategy_family,
                            "strategy_label": STRATEGY_LABELS[strategy_family],
                            "regime": regime,
                            "regime_label": REGIME_LABELS[regime],
                            "min_score": threshold,
                            "cost_bps": cost_bps,
                            "resolved_signals": len(scoped),
                            "distinct_tickers": len({item.ticker for item in scoped}),
                            "distinct_signal_dates": len({item.signal_date for item in scoped}),
                            "gross_expectancy_pct": _round_optional(gross),
                            "net_expectancy_pct": _round_optional(net),
                            "oos_resolved_signals": len(evaluation_rows),
                            "oos_distinct_tickers": len(
                                {item.ticker for item in evaluation_rows}
                            ),
                            "oos_distinct_signal_dates": len(
                                {item.signal_date for item in evaluation_rows}
                            ),
                            "oos_gross_expectancy_pct": _round_optional(oos_gross),
                            "oos_net_expectancy_pct": _round_optional(oos_net),
                            "oos_win_rate_pct": _win_rate(
                                evaluation_rows,
                                cost_bps=cost_bps,
                            ),
                            "confidence_interval_low_pct": _round_optional(low),
                            "confidence_interval_high_pct": _round_optional(high),
                            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
                            "validation_basis": (
                                "walk_forward_oos"
                                if valid_validation_dates
                                else "in_sample_fallback"
                            ),
                            "evidence_level": evidence_level,
                            "eligible_fold_count": len(fold_expectancies),
                            "positive_fold_count": sum(
                                1
                                for value in fold_expectancies
                                if value - ((cost_bps - DEFAULT_COST_SCENARIO_BPS) / 100)
                                > 0
                            ),
                            "fold_net_expectancy_pct": [
                                round(
                                    value
                                    - (
                                        (cost_bps - DEFAULT_COST_SCENARIO_BPS)
                                        / 100
                                    ),
                                    2,
                                )
                                for value in fold_expectancies
                            ],
                        }
                        payload.append(row)
                segment_number += 1
        self._annotate_stability_and_verdict(payload)
        return payload

    def _fold_expectancies(
        self,
        observations: Sequence[CalibrationObservation],
        *,
        folds: Sequence[WalkForwardFold],
        cost_bps: int,
    ) -> list[float]:
        payload: list[float] = []
        for fold in folds:
            if not fold.eligible:
                continue
            fold_rows = [
                row for row in observations if row.signal_date in set(fold.validation_dates)
            ]
            expectancy = _mean_return(fold_rows)
            if expectancy is not None:
                payload.append(expectancy - (cost_bps / 100))
        return payload

    def _annotate_stability_and_verdict(
        self,
        sensitivity: list[dict[str, Any]],
    ) -> None:
        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in sensitivity:
            grouped[
                (
                    str(row["strategy_family"]),
                    str(row["regime"]),
                    int(row["cost_bps"]),
                )
            ].append(row)
        for rows in grouped.values():
            rows.sort(key=lambda row: int(row["min_score"]))
            for index, row in enumerate(rows):
                neighbors = [
                    rows[position]
                    for position in (index - 1, index + 1)
                    if 0 <= position < len(rows)
                ]
                stable_neighbors = bool(neighbors) and all(
                    item["oos_net_expectancy_pct"] is not None
                    and float(item["oos_net_expectancy_pct"]) > 0
                    for item in neighbors
                )
                row["stable_neighbors"] = stable_neighbors
                row["verdict"] = self._verdict(row)

    @staticmethod
    def _verdict(row: Mapping[str, Any]) -> str:
        if row["validation_basis"] != "walk_forward_oos":
            return "insufficient"
        if row["evidence_level"] == "insufficient":
            return "insufficient"
        fold_count = int(row["eligible_fold_count"])
        positive_fold_count = int(row["positive_fold_count"])
        required_positive = max(1, math.ceil(fold_count * 2 / 3))
        if (
            fold_count < 2
            or positive_fold_count < required_positive
            or not row["stable_neighbors"]
        ):
            return "unstable"
        oos_net = row["oos_net_expectancy_pct"]
        if oos_net is None or float(oos_net) <= 0:
            return "negative"
        interval_low = row["confidence_interval_low_pct"]
        if (
            row["evidence_level"] == "established"
            and interval_low is not None
            and float(interval_low) > 0
        ):
            return "strong_shadow_candidate"
        return "promising_for_shadow"

    def _build_candidate_comparisons(
        self,
        sensitivity: Sequence[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in sensitivity:
            if int(row["cost_bps"]) == DEFAULT_COST_SCENARIO_BPS:
                grouped[(str(row["strategy_family"]), str(row["regime"]))].append(row)
        payload: list[dict[str, Any]] = []
        for (strategy_family, regime), rows in grouped.items():
            current = next(
                (row for row in rows if int(row["min_score"]) == MIN_EXECUTION_SCORE),
                rows[0],
            )
            established = [row for row in rows if row["evidence_level"] == "established"]
            developing = [row for row in rows if row["evidence_level"] == "developing"]
            eligible = established or developing
            candidate = (
                max(eligible, key=self._candidate_sort_key)
                if eligible
                else current
            )
            changed = int(candidate["min_score"]) != int(current["min_score"])
            reasons = self._candidate_reasons(candidate, current=current, changed=changed)
            payload.append(
                {
                    "strategy_family": strategy_family,
                    "strategy_label": STRATEGY_LABELS[strategy_family],
                    "regime": regime,
                    "regime_label": REGIME_LABELS[regime],
                    "cost_bps": DEFAULT_COST_SCENARIO_BPS,
                    "current": dict(current),
                    "candidate": dict(candidate),
                    "threshold_delta": int(candidate["min_score"])
                    - int(current["min_score"]),
                    "expectancy_delta_pct": _round_optional(
                        _subtract_optional(
                            candidate["oos_net_expectancy_pct"],
                            current["oos_net_expectancy_pct"],
                        )
                    ),
                    "verdict": candidate["verdict"],
                    "changed": changed,
                    "deployment_status": "research_only_no_config_change",
                    "reasons": reasons,
                }
            )
        return payload

    @staticmethod
    def _candidate_sort_key(row: Mapping[str, Any]) -> tuple[float, float, int, int]:
        interval_low = row["confidence_interval_low_pct"]
        expectancy = row["oos_net_expectancy_pct"]
        return (
            float(interval_low) if interval_low is not None else float("-inf"),
            float(expectancy) if expectancy is not None else float("-inf"),
            int(row["oos_resolved_signals"]),
            -int(row["min_score"]),
        )

    @staticmethod
    def _candidate_reasons(
        candidate: Mapping[str, Any],
        *,
        current: Mapping[str, Any],
        changed: bool,
    ) -> list[str]:
        reasons = [
            (
                f"{candidate['evidence_level'].capitalize()} evidence: "
                f"{candidate['oos_resolved_signals']} OOS outcomes across "
                f"{candidate['oos_distinct_signal_dates']} signal dates."
            ),
            (
                f"{candidate['positive_fold_count']} of "
                f"{candidate['eligible_fold_count']} eligible folds are positive "
                "after 10 bps costs."
            ),
        ]
        if candidate["confidence_interval_low_pct"] is None:
            reasons.append("The clustered interval is unavailable because time clusters are too sparse.")
        elif float(candidate["confidence_interval_low_pct"]) <= 0:
            reasons.append("The clustered uncertainty interval still crosses zero.")
        else:
            reasons.append("The clustered uncertainty interval remains above zero.")
        if not candidate["stable_neighbors"]:
            reasons.append("Adjacent score thresholds do not confirm a stable positive plateau.")
        if not changed:
            reasons.append("The current threshold remains the research baseline for this segment.")
        elif current["oos_net_expectancy_pct"] is not None:
            reasons.append(
                f"The selected shadow threshold is {candidate['min_score']} versus "
                f"the current {current['min_score']}."
            )
        return reasons

    def _build_confidence_reliability(
        self,
        observations: Sequence[CalibrationObservation],
        *,
        valid_validation_dates: set[date],
        has_eligible_folds: bool,
    ) -> dict[str, Any]:
        eligible = [row for row in observations if row.score >= min(SCORE_THRESHOLDS)]
        rows: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for strategy_family in STRATEGY_LABELS:
            strategy_rows = [
                row for row in eligible if row.strategy_family == strategy_family
            ]
            evaluation_rows = (
                [
                    row
                    for row in strategy_rows
                    if row.signal_date in valid_validation_dates
                ]
                if has_eligible_folds
                else strategy_rows
            )
            base_wins = sum(
                1
                for row in evaluation_rows
                if row.realized_return_pct - DEFAULT_COST_SCENARIO_BPS / 100 > 0
            )
            base_rate = base_wins / len(evaluation_rows) if evaluation_rows else 0.5
            strategy_band_rows: list[dict[str, Any]] = []
            bands = sorted(
                {row.confidence_band for row in strategy_rows},
                key=lambda band: (CONFIDENCE_ORDER.get(band, 999), band),
            )
            for band_index, band in enumerate(bands):
                band_rows = [
                    row for row in evaluation_rows if row.confidence_band == band
                ]
                wins = sum(
                    1
                    for row in band_rows
                    if row.realized_return_pct - DEFAULT_COST_SCENARIO_BPS / 100 > 0
                )
                observed_rate = wins / len(band_rows) * 100 if band_rows else None
                smoothed_rate = (
                    (wins + base_rate * 20) / (len(band_rows) + 20) * 100
                    if band_rows
                    else None
                )
                interval = self._cluster_bootstrap_interval(
                    band_rows,
                    value=lambda row: (
                        1.0
                        if row.realized_return_pct
                        - DEFAULT_COST_SCENARIO_BPS / 100
                        > 0
                        else 0.0
                    ),
                    seed_offset=9000 + band_index + len(rows),
                )
                reliability_row = {
                    "strategy_family": strategy_family,
                    "strategy_label": STRATEGY_LABELS[strategy_family],
                    "confidence_band": band,
                    "resolved_signals": len(band_rows),
                    "distinct_signal_dates": len(
                        {row.signal_date for row in band_rows}
                    ),
                    "observed_success_rate_pct": _round_optional(observed_rate),
                    "shrunk_reference_rate_pct": _round_optional(smoothed_rate),
                    "confidence_interval_low_pct": (
                        round(interval[0] * 100, 1) if interval else None
                    ),
                    "confidence_interval_high_pct": (
                        round(interval[1] * 100, 1) if interval else None
                    ),
                    "evidence_level": self._evidence_level(band_rows),
                    "validation_basis": (
                        "walk_forward_oos"
                        if has_eligible_folds
                        else "in_sample_fallback"
                    ),
                }
                rows.append(reliability_row)
                strategy_band_rows.append(reliability_row)
            comparable = [
                row
                for row in strategy_band_rows
                if row["observed_success_rate_pct"] is not None
                and row["evidence_level"] != "insufficient"
            ]
            monotonic = len(comparable) >= 2 and all(
                float(current["shrunk_reference_rate_pct"])
                >= float(previous["shrunk_reference_rate_pct"])
                for previous, current in zip(comparable, comparable[1:])
            )
            diagnostics.append(
                {
                    "strategy_family": strategy_family,
                    "strategy_label": STRATEGY_LABELS[strategy_family],
                    "status": (
                        "aligned"
                        if monotonic
                        else "not_aligned"
                        if len(comparable) >= 2
                        else "insufficient"
                    ),
                    "comparable_bands": len(comparable),
                }
            )
        return {
            "probability_scoring_available": False,
            "brier_score": None,
            "reason": (
                "Confidence is stored as an ordinal label, not a numeric probability. "
                "Brier score and probability calibration would be misleading."
            ),
            "research_reference": (
                "The shrunk success rate is a descriptive shadow reference after 10 bps costs; "
                "it does not rewrite confidence labels."
            ),
            "rows": rows,
            "diagnostics": diagnostics,
        }

    def _cluster_bootstrap_interval(
        self,
        observations: Sequence[CalibrationObservation],
        *,
        value: Callable[[CalibrationObservation], float],
        seed_offset: int,
    ) -> tuple[float, float] | None:
        by_date: dict[date, dict[str, list[CalibrationObservation]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for row in observations:
            by_date[row.signal_date][row.ticker].append(row)
        signal_dates = sorted(by_date)
        if len(signal_dates) < 2:
            return None
        rng = random.Random(self._bootstrap_seed + seed_offset)
        estimates: list[float] = []
        for _ in range(self._bootstrap_iterations):
            sampled_values: list[float] = []
            for _ in signal_dates:
                sampled_date = rng.choice(signal_dates)
                ticker_groups = list(by_date[sampled_date].values())
                for _ in ticker_groups:
                    sampled_values.extend(
                        value(row) for row in rng.choice(ticker_groups)
                    )
            if sampled_values:
                estimates.append(fmean(sampled_values))
        if not estimates:
            return None
        alpha = (1 - BOOTSTRAP_CONFIDENCE_LEVEL) / 2
        estimates.sort()
        return (
            _quantile(estimates, alpha),
            _quantile(estimates, 1 - alpha),
        )

    @staticmethod
    def _evidence_level(
        observations: Sequence[CalibrationObservation],
    ) -> str:
        signal_count = len(observations)
        date_count = len({row.signal_date for row in observations})
        if signal_count >= 50 and date_count >= 12:
            return "established"
        if signal_count >= 30 and date_count >= 8:
            return "developing"
        return "insufficient"

    @staticmethod
    def _fold_payload(fold: WalkForwardFold) -> dict[str, Any]:
        return {
            "fold": fold.fold,
            "training_end": fold.training_end.isoformat(),
            "validation_start": fold.validation_start.isoformat(),
            "validation_end": fold.validation_end.isoformat(),
            "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
            "training_observations": fold.training_observations,
            "training_signal_dates": fold.training_signal_dates,
            "validation_observations": fold.validation_observations,
            "validation_signal_dates": fold.validation_signal_dates,
            "eligible": fold.eligible,
        }


def _regime_from_row(row: Mapping[str, Any]) -> str:
    try:
        snapshot = json.loads(row["feature_snapshot_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    regime = str(snapshot.get("regime_label") or "").upper().strip()
    if regime in REGIME_LABELS:
        return regime
    setup_type = str(row["setup_type"] or "").lower()
    if any(term in setup_type for term in ("mean", "reversion", "pullback")):
        return "MEAN_REVERSION"
    if setup_type and setup_type != "manual":
        return "MOMENTUM"
    return "UNKNOWN"


def _parse_date(value: Any) -> date:
    normalized = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).date()


def _split_dates(values: Sequence[date], parts: int) -> list[list[date]]:
    if not values or parts <= 0:
        return []
    quotient, remainder = divmod(len(values), parts)
    blocks: list[list[date]] = []
    start = 0
    for index in range(parts):
        width = quotient + (1 if index < remainder else 0)
        blocks.append(list(values[start : start + width]))
        start += width
    return [block for block in blocks if block]


def _mean_return(observations: Iterable[CalibrationObservation]) -> float | None:
    values = [row.realized_return_pct for row in observations]
    return fmean(values) if values else None


def _win_rate(
    observations: Sequence[CalibrationObservation],
    *,
    cost_bps: int,
) -> float | None:
    if not observations:
        return None
    cost_pct = cost_bps / 100
    wins = sum(1 for row in observations if row.realized_return_pct - cost_pct > 0)
    return round(wins / len(observations) * 100, 1)


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(
        sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    )


def _subtract_optional(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return float(left) - float(right)


def _round_optional(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


__all__ = [
    "CalibrationObservation",
    "CalibrationResearchService",
    "COST_SCENARIOS_BPS",
    "SCORE_THRESHOLDS",
]
