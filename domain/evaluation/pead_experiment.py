from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor
from statistics import fmean, median
from typing import Any, Callable, Literal, Never, Sequence

from domain.scoring.pead_shadow import PEAD_HORIZONS, PRICE_STORE_MIN_SESSIONS


# Pre-registered protocol. Do not retune after seeing results.
PROTOCOL_VERSION = "pead_shadow_v1_2026-09-14"
HORIZONS: tuple[int, ...] = PEAD_HORIZONS
INCREMENTAL_HORIZONS: tuple[int, ...] = (20, 60)
SURPRISE_ABS_CUTS_PCT: tuple[float, ...] = (5.0, 10.0, 20.0)
PRIMARY_SURPRISE_ABS_PCT = 5.0
PRIMARY_BENCHMARK = "spy"
RETURN_DEFINITION = (
    "close_to_close: last close strictly before event_date to the Nth session "
    "on or after event_date, computed independently for stock, SPY, and sector ETF"
)
EVENT_DATE_PREFERENCE = (
    "earliest unused SEC 8-K item 2.02 filing within 120 calendar days on or after "
    "the fiscal period end; otherwise fiscal period end (explicitly labeled fiscal_period)"
)
COST_BPS = 10
ECONOMIC_INCREMENT_PP = 0.50
BOOTSTRAP_CONFIDENCE_LEVEL = 0.90
BOOTSTRAP_ITERATIONS = 500
BOOTSTRAP_SEED = 20260914
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 15
MIN_UNIQUE_EVENT_DATES_FOR_FOLDS = 8
MIN_PRIMARY_N_BY_HORIZON: dict[int, int] = {10: 40, 20: 40, 60: 25}
MIN_PRIMARY_OOS_N_BY_HORIZON: dict[int, int] = {10: 15, 20: 15, 60: 12}
MIN_TRAINING_EVENTS_FOR_FOLD = 20
MIN_TRAINING_DATES_FOR_FOLD = 4
PRICE_STORE_PERIOD = "2y"

PeadVerdict = Literal["success", "fail", "data_blocked"]
SurpriseSign = Literal["beat", "miss"]


@dataclass(frozen=True)
class PeadHorizonObservation:
    sessions: int
    complete: bool
    stock_return_pct: float | None
    market_excess_pct: float | None
    sector_excess_pct: float | None


@dataclass(frozen=True)
class PeadEventObservation:
    ticker: str
    event_date: date
    period: str
    surprise_pct: float
    surprise_sign: SurpriseSign
    event_date_source: str
    sector: str
    size_bucket: str
    market_cap: float | None
    horizons: tuple[PeadHorizonObservation, ...]

    def horizon(self, sessions: int) -> PeadHorizonObservation | None:
        for item in self.horizons:
            if item.sessions == sessions:
                return item
        return None

    def aligned_excess(
        self,
        sessions: int,
        *,
        benchmark: str = PRIMARY_BENCHMARK,
    ) -> float | None:
        row = self.horizon(sessions)
        if row is None or not row.complete:
            return None
        excess = row.market_excess_pct if benchmark == "spy" else row.sector_excess_pct
        if excess is None:
            return None
        direction = 1.0 if self.surprise_sign == "beat" else -1.0
        return direction * float(excess)


def surprise_sign(surprise_pct: float) -> SurpriseSign | None:
    if surprise_pct > 0.1:
        return "beat"
    if surprise_pct < -0.1:
        return "miss"
    return None


def surprise_bucket_label(abs_cut: float) -> str:
    return f"|surprise| >= {abs_cut:g}%"


def in_surprise_bucket(event: PeadEventObservation, abs_cut: float) -> bool:
    return abs(event.surprise_pct) >= abs_cut


def cost_pct() -> float:
    return COST_BPS / 100.0


def complete_aligned_values(
    events: Sequence[PeadEventObservation],
    sessions: int,
    *,
    benchmark: str = PRIMARY_BENCHMARK,
) -> list[float]:
    values: list[float] = []
    for event in events:
        value = event.aligned_excess(sessions, benchmark=benchmark)
        if value is not None:
            values.append(value)
    return values


def incremental_aligned_values(
    events: Sequence[PeadEventObservation],
    sessions: int,
    *,
    benchmark: str = PRIMARY_BENCHMARK,
) -> list[float]:
    values: list[float] = []
    for event in events:
        later = event.aligned_excess(sessions, benchmark=benchmark)
        baseline = event.aligned_excess(3, benchmark=benchmark)
        if later is None or baseline is None:
            continue
        values.append(later - baseline)
    return values


def sample_stats(values: Sequence[float], *, cost: float = 0.0) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean_pct": None,
            "median_pct": None,
            "hit_rate_pct": None,
            "mean_after_cost_pct": None,
        }
    after_cost = [value - cost for value in values]
    return {
        "n": len(values),
        "mean_pct": round(fmean(values), 4),
        "median_pct": round(median(values), 4),
        "hit_rate_pct": round(sum(value > 0 for value in after_cost) / len(after_cost) * 100, 1),
        "mean_after_cost_pct": round(fmean(after_cost), 4),
    }


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    cluster_keys: Sequence[date] | None = None,
    confidence_level: float = BOOTSTRAP_CONFIDENCE_LEVEL,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
    seed_offset: int = 0,
) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng_seed = seed + seed_offset
    estimates: list[float] = []
    if cluster_keys is None or len(cluster_keys) != len(values):
        rng = random.Random(rng_seed)
        population = list(values)
        for _ in range(iterations):
            sample = [population[rng.randrange(len(population))] for _ in population]
            estimates.append(fmean(sample))
    else:
        grouped: dict[date, list[float]] = {}
        for key, value in zip(cluster_keys, values):
            grouped.setdefault(key, []).append(value)
        dates = list(grouped)
        rng = random.Random(rng_seed)
        for _ in range(iterations):
            sampled: list[float] = []
            for _date in range(len(dates)):
                chosen = dates[rng.randrange(len(dates))]
                sampled.extend(grouped[chosen])
            if sampled:
                estimates.append(fmean(sampled))
    if not estimates:
        return None
    estimates.sort()
    alpha = (1 - confidence_level) / 2
    return (_quantile(estimates, alpha), _quantile(estimates, 1 - alpha))


def interval_excludes_zero(interval: tuple[float, float] | None) -> bool:
    if interval is None:
        return False
    low, high = interval
    return high < 0 or low > 0


def walk_forward_date_blocks(event_dates: Sequence[date]) -> list[dict[str, Any]]:
    unique_dates = sorted(set(event_dates))
    if len(unique_dates) < MIN_UNIQUE_EVENT_DATES_FOR_FOLDS:
        return []
    initial_training = max(4, ceil(len(unique_dates) * 0.40))
    validation_pool = unique_dates[initial_training:]
    blocks = _split_dates(validation_pool, min(WALK_FORWARD_FOLDS, len(validation_pool)))
    folds: list[dict[str, Any]] = []
    for index, validation_dates in enumerate(blocks, start=1):
        validation_start = validation_dates[0]
        training_end = validation_start - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)
        training_dates = [item for item in unique_dates if item <= training_end]
        eligible = (
            len(training_dates) >= MIN_TRAINING_DATES_FOR_FOLD
        )
        folds.append(
            {
                "fold": index,
                "training_end": training_end,
                "validation_start": validation_start,
                "validation_end": validation_dates[-1],
                "validation_dates": tuple(validation_dates),
                "training_dates": tuple(training_dates),
                "eligible": eligible,
            }
        )
    return folds


def oos_events(
    events: Sequence[PeadEventObservation],
    folds: Sequence[dict[str, Any]],
) -> list[PeadEventObservation]:
    oos_dates = {
        event_date
        for fold in folds
        if fold["eligible"]
        for event_date in fold["validation_dates"]
    }
    return [event for event in events if event.event_date in oos_dates]


def evaluate_horizon(
    events: Sequence[PeadEventObservation],
    oos: Sequence[PeadEventObservation],
    sessions: int,
    *,
    benchmark: str = PRIMARY_BENCHMARK,
    seed_offset: int = 0,
) -> dict[str, Any]:
    required_n = MIN_PRIMARY_N_BY_HORIZON[sessions]
    required_oos = MIN_PRIMARY_OOS_N_BY_HORIZON[sessions]
    in_sample_values = complete_aligned_values(events, sessions, benchmark=benchmark)
    oos_values = complete_aligned_values(oos, sessions, benchmark=benchmark)
    incremental = incremental_aligned_values(oos, sessions, benchmark=benchmark)
    in_sample_n = len(in_sample_values)
    oos_n = len(oos_values)
    testable = in_sample_n >= required_n and oos_n >= required_oos and len(incremental) >= required_oos
    cost = cost_pct()
    oos_after_cost = [value - cost for value in oos_values]
    oos_cluster = [event.event_date for event in oos if event.aligned_excess(sessions, benchmark=benchmark) is not None]
    incremental_cluster = [
        event.event_date
        for event in oos
        if event.aligned_excess(sessions, benchmark=benchmark) is not None
        and event.aligned_excess(3, benchmark=benchmark) is not None
    ]
    mean_interval = bootstrap_mean_interval(
        oos_after_cost,
        cluster_keys=oos_cluster,
        seed_offset=seed_offset,
    )
    increment_interval = bootstrap_mean_interval(
        incremental,
        cluster_keys=incremental_cluster,
        seed_offset=seed_offset + 17,
    )
    mean_after_cost = fmean(oos_after_cost) if oos_after_cost else None
    increment_mean = fmean(incremental) if incremental else None
    distinguishable = interval_excludes_zero(mean_interval) and (
        mean_after_cost is not None and mean_after_cost > 0
    )
    economic = (
        increment_mean is not None
        and increment_mean >= ECONOMIC_INCREMENT_PP
        and interval_excludes_zero(increment_interval)
        and increment_interval is not None
        and increment_interval[0] > 0
    )
    passed = bool(testable and distinguishable and economic)
    return {
        "sessions": sessions,
        "benchmark": benchmark,
        "required_n": required_n,
        "required_oos_n": required_oos,
        "in_sample_n": in_sample_n,
        "oos_n": oos_n,
        "testable": testable,
        "data_blocked": not testable,
        "in_sample": sample_stats(in_sample_values, cost=cost),
        "oos": sample_stats(oos_values, cost=cost),
        "incremental_vs_3_session": {
            **sample_stats(incremental, cost=0.0),
            "economic_threshold_pp": ECONOMIC_INCREMENT_PP,
            "mean_gross_increment_pct": round(increment_mean, 4) if increment_mean is not None else None,
        },
        "bootstrap": {
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
            "iterations": BOOTSTRAP_ITERATIONS,
            "mean_after_cost_ci": _round_interval(mean_interval),
            "increment_ci": _round_interval(increment_interval),
            "mean_ci_excludes_zero": interval_excludes_zero(mean_interval),
            "increment_ci_excludes_zero": interval_excludes_zero(increment_interval),
        },
        "distinguishable_from_zero": distinguishable,
        "economically_nontrivial_vs_session_3": economic,
        "passed": passed,
    }


def decide_verdict(horizon_results: Sequence[dict[str, Any]]) -> PeadVerdict:
    confirmatory = [
        row for row in horizon_results if int(row["sessions"]) in INCREMENTAL_HORIZONS
    ]
    if not confirmatory:
        return "data_blocked"
    if any(row["passed"] for row in confirmatory):
        return "success"
    if any(row["testable"] for row in confirmatory):
        return "fail"
    return "data_blocked"


def verdict_status(verdict: PeadVerdict) -> str:
    match verdict:
        case "success":
            return "Hypothesis supported"
        case "fail":
            return "Hypothesis not supported"
        case "data_blocked":
            return "Data blocked"
        case _:
            unreachable: Never = verdict
            raise ValueError(unreachable)


def protocol_payload() -> dict[str, Any]:
    return {
        "version": PROTOCOL_VERSION,
        "mode": "shadow",
        "automatic_activation": False,
        "live_score_changes": False,
        "horizons": list(HORIZONS),
        "confirmatory_horizons": list(INCREMENTAL_HORIZONS),
        "surprise_abs_cuts_pct": list(SURPRISE_ABS_CUTS_PCT),
        "primary_surprise_abs_pct": PRIMARY_SURPRISE_ABS_PCT,
        "primary_bucket": surprise_bucket_label(PRIMARY_SURPRISE_ABS_PCT),
        "primary_benchmark": PRIMARY_BENCHMARK,
        "primary_metric": "surprise_aligned_spy_excess_after_cost",
        "return_definition": RETURN_DEFINITION,
        "event_date_preference": EVENT_DATE_PREFERENCE,
        "cost_bps": COST_BPS,
        "economic_increment_pp": ECONOMIC_INCREMENT_PP,
        "bootstrap": {
            "method": "event_date_cluster_bootstrap",
            "confidence_level": BOOTSTRAP_CONFIDENCE_LEVEL,
            "iterations": BOOTSTRAP_ITERATIONS,
            "seed": BOOTSTRAP_SEED,
        },
        "walk_forward": {
            "folds": WALK_FORWARD_FOLDS,
            "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
            "split_basis": "event_date",
            "design": "expanding_window_with_calendar_embargo",
        },
        "abort_criteria": {
            "minimum_primary_n_by_horizon": dict(MIN_PRIMARY_N_BY_HORIZON),
            "minimum_primary_oos_n_by_horizon": dict(MIN_PRIMARY_OOS_N_BY_HORIZON),
            "rule": (
                "If neither confirmatory horizon (20, 60) is testable, abort as "
                "data-blocked rather than fail-of-hypothesis."
            ),
        },
        "price_store": {
            "period": PRICE_STORE_PERIOD,
            "minimum_sessions_warning": PRICE_STORE_MIN_SESSIONS,
            "note": (
                "Stock and SPY/sector ETF daily history is fetched with period=2y "
                "(~504 sessions). Last-four-quarter events plus 60 post-event sessions "
                "fit that window; recent events remain incomplete until enough sessions elapse."
            ),
        },
        "secondary_only": [
            "size_bucket",
            "sector",
            "|surprise| >= 10%",
            "|surprise| >= 20%",
            "sector_excess",
            "session 10",
        ],
    }


def decay_curve(
    events: Sequence[PeadEventObservation],
    *,
    benchmark: str = PRIMARY_BENCHMARK,
) -> list[dict[str, Any]]:
    curve: list[dict[str, Any]] = []
    for sessions in HORIZONS:
        values = complete_aligned_values(events, sessions, benchmark=benchmark)
        curve.append(
            {
                "sessions": sessions,
                "benchmark": benchmark,
                **sample_stats(values, cost=cost_pct()),
            }
        )
    return curve


def descriptive_strata(
    events: Sequence[PeadEventObservation],
    sessions: int,
    *,
    key: Callable[[PeadEventObservation], str],
    label: str,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[PeadEventObservation]] = {}
    for event in events:
        grouped.setdefault(key(event), []).append(event)
    rows: list[dict[str, Any]] = []
    for name in sorted(grouped):
        scoped = grouped[name]
        values = complete_aligned_values(scoped, sessions)
        rows.append(
            {
                label: name,
                "sessions": sessions,
                "role": "descriptive_only",
                **sample_stats(values, cost=cost_pct()),
            }
        )
    return rows


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


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _round_interval(interval: tuple[float, float] | None) -> list[float] | None:
    if interval is None:
        return None
    return [round(interval[0], 4), round(interval[1], 4)]


__all__ = [
    "BOOTSTRAP_CONFIDENCE_LEVEL",
    "BOOTSTRAP_ITERATIONS",
    "BOOTSTRAP_SEED",
    "COST_BPS",
    "ECONOMIC_INCREMENT_PP",
    "HORIZONS",
    "INCREMENTAL_HORIZONS",
    "MIN_PRIMARY_N_BY_HORIZON",
    "MIN_PRIMARY_OOS_N_BY_HORIZON",
    "PEAD_HORIZONS",
    "PRIMARY_SURPRISE_ABS_PCT",
    "PROTOCOL_VERSION",
    "PeadEventObservation",
    "PeadHorizonObservation",
    "PeadVerdict",
    "SURPRISE_ABS_CUTS_PCT",
    "complete_aligned_values",
    "cost_pct",
    "decay_curve",
    "decide_verdict",
    "descriptive_strata",
    "evaluate_horizon",
    "in_surprise_bucket",
    "incremental_aligned_values",
    "oos_events",
    "protocol_payload",
    "sample_stats",
    "surprise_bucket_label",
    "surprise_sign",
    "verdict_status",
    "walk_forward_date_blocks",
]
