from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import pandas as pd

from config.nfci_regime import (
    DELTA_WEEKS,
    HY_KEEP_RECIPE_VERSION,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_PERCENTILE_MIN_OBSERVATIONS,
    HY_PERCENTILE_THROTTLE,
    HY_PERCENTILE_WINDOW_SESSIONS,
    HY_VELOCITY_WIDENING_BP,
    HY_VELOCITY_WINDOW_SESSIONS,
    HY_WEEKLY_WINDOW_SESSIONS,
    ICE_REDISTRIBUTION_NOTICE,
    MIN_NFCI_WEEKS_HARD,
    MIN_NFCI_WEEKS_RECOMMENDED,
    NFCI_MODE,
    NFCI_RECIPE_VERSION,
    PERSISTENCE_WEEKS,
    SPY_VOL_WINDOW_SESSIONS,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    nfci_recipe_manifest,
)
from providers.macro.nfci_client import HyKeepObservation, NfciSeriesBundle


GateStatus = Literal["full", "throttle", "unknown"]


@dataclass(frozen=True)
class NfciGateDecision:
    status: GateStatus
    nfci: float | None
    nfci_d4w: float | None
    rising_streak: int
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = NFCI_RECIPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class HyKeepGateDecision:
    status: GateStatus
    hy_oas: float | None
    hy_oas_d20_bp: float | None
    hy_oas_percentile_252: float | None
    percentile_observations: int
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = HY_KEEP_RECIPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class NfciWeeklySnapshot:
    observation_week_end: date
    release_date: date
    nfci: float | None
    nfci_d4w: float | None
    rising_streak: int
    persistence_rising: bool
    spy_return_pct: float | None
    spy_realized_vol_20d: float | None
    gate: NfciGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observation_week_end"] = self.observation_week_end.isoformat()
        payload["release_date"] = self.release_date.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class HyKeepDailySnapshot:
    as_of: date
    hy_oas: float | None
    ig_oas: float | None
    hy_ig_gap: float | None
    hy_oas_d20_bp: float | None
    hy_oas_d5_bp: float | None
    hy_oas_percentile_252: float | None
    percentile_observations: int
    gate: HyKeepGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class NfciRegimeView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    recipe_version: str
    as_of_date: str | None
    snapshot: dict[str, Any] | None
    gate: dict[str, Any]
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NfciPanel:
    recipe: dict[str, Any]
    rows: tuple[NfciWeeklySnapshot, ...]
    source: str
    nfci_count: int
    history_weeks: int
    coverage: dict[str, Any]
    abort_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "source": self.source,
            "nfci_count": self.nfci_count,
            "history_weeks": self.history_weeks,
            "coverage": self.coverage,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> NfciWeeklySnapshot | None:
        """Latest print whose release_date is on or before as_of. No week-end look-ahead."""
        chosen: NfciWeeklySnapshot | None = None
        for row in self.rows:
            if row.release_date <= as_of:
                chosen = row
            elif chosen is not None:
                break
        return chosen

    def gate_status_on(self, as_of: date) -> GateStatus:
        snapshot = self.snapshot_on(as_of)
        if snapshot is None:
            return "unknown"
        return snapshot.gate.status


@dataclass(frozen=True)
class HyKeepPanel:
    recipe: dict[str, Any]
    rows: tuple[HyKeepDailySnapshot, ...]
    hy_count: int
    ig_count: int
    abort_reasons: tuple[str, ...]
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "hy_count": self.hy_count,
            "ig_count": self.ig_count,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> HyKeepDailySnapshot | None:
        chosen: HyKeepDailySnapshot | None = None
        for row in self.rows:
            if row.as_of <= as_of:
                chosen = row
            elif chosen is not None:
                break
        return chosen


def gate_status_label(status: GateStatus) -> str:
    match status:
        case "full":
            return "full"
        case "throttle":
            return "throttle"
        case "unknown":
            return "unknown"
        case _ as unreachable:
            assert_never(unreachable)


def evaluate_nfci_gate(
    *,
    nfci: float | None,
    nfci_d4w: float | None,
    rising_streak: int,
) -> NfciGateDecision:
    reasons: list[str] = []
    if nfci is None or nfci_d4w is None:
        reasons.append("NFCI level or 4-week change is missing on the release-dated panel.")
        return NfciGateDecision(
            status="unknown",
            nfci=nfci,
            nfci_d4w=nfci_d4w,
            rising_streak=rising_streak,
            throttle_weight=None,
            reasons=tuple(reasons),
        )
    if rising_streak >= PERSISTENCE_WEEKS:
        reasons.append(
            f"NFCI 4-week change is {nfci_d4w:.3f} and has been strictly positive for "
            f"{rising_streak} consecutive weekly prints (frozen N={PERSISTENCE_WEEKS})."
        )
        reasons.append(
            f"Long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
        return NfciGateDecision(
            status="throttle",
            nfci=nfci,
            nfci_d4w=nfci_d4w,
            rising_streak=rising_streak,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=tuple(reasons),
        )
    reasons.append(
        f"NFCI level is {nfci:.3f} with 4-week Δ {nfci_d4w:.3f} and a rising streak of "
        f"{rising_streak} (need {PERSISTENCE_WEEKS}). The frozen throttle is not engaged."
    )
    return NfciGateDecision(
        status="full",
        nfci=nfci,
        nfci_d4w=nfci_d4w,
        rising_streak=rising_streak,
        throttle_weight=1.0,
        reasons=tuple(reasons),
    )


def evaluate_hy_keep_gate(
    *,
    hy_oas: float | None,
    hy_oas_d20_bp: float | None,
    hy_oas_percentile_252: float | None,
    percentile_observations: int,
) -> HyKeepGateDecision:
    reasons: list[str] = []
    if hy_oas is None or hy_oas_d20_bp is None:
        reasons.append("HY OAS level or 20-session change is missing.")
        return HyKeepGateDecision(
            status="unknown",
            hy_oas=hy_oas,
            hy_oas_d20_bp=hy_oas_d20_bp,
            hy_oas_percentile_252=hy_oas_percentile_252,
            percentile_observations=percentile_observations,
            throttle_weight=None,
            reasons=tuple(reasons),
        )
    velocity_hit = hy_oas_d20_bp > HY_VELOCITY_WIDENING_BP
    percentile_ready = (
        percentile_observations >= HY_PERCENTILE_MIN_OBSERVATIONS
        and hy_oas_percentile_252 is not None
    )
    percentile_hit = percentile_ready and hy_oas_percentile_252 >= HY_PERCENTILE_THROTTLE
    if velocity_hit:
        reasons.append(
            f"20-session HY OAS change is {hy_oas_d20_bp:.1f} bp, above the discovered "
            f"KEEP {HY_VELOCITY_WIDENING_BP:.0f} bp widening threshold."
        )
    if percentile_hit:
        reasons.append(
            f"Causal trailing-{HY_PERCENTILE_WINDOW_SESSIONS} HY OAS percentile is "
            f"{hy_oas_percentile_252:.1f}, at or above {HY_PERCENTILE_THROTTLE:.0f}."
        )
    if velocity_hit or percentile_hit:
        reasons.append(
            f"KEEP long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
        return HyKeepGateDecision(
            status="throttle",
            hy_oas=hy_oas,
            hy_oas_d20_bp=hy_oas_d20_bp,
            hy_oas_percentile_252=hy_oas_percentile_252,
            percentile_observations=percentile_observations,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=tuple(reasons),
        )
    reasons.append(
        f"20-session HY OAS change is {hy_oas_d20_bp:.1f} bp and the causal "
        f"trailing percentile is "
        f"{'n/a' if hy_oas_percentile_252 is None else f'{hy_oas_percentile_252:.1f}'}; "
        "the discovered KEEP throttle is not engaged."
    )
    return HyKeepGateDecision(
        status="full",
        hy_oas=hy_oas,
        hy_oas_d20_bp=hy_oas_d20_bp,
        hy_oas_percentile_252=hy_oas_percentile_252,
        percentile_observations=percentile_observations,
        throttle_weight=1.0,
        reasons=tuple(reasons),
    )


def build_nfci_panel(
    bundle: NfciSeriesBundle,
    *,
    spy_history: pd.DataFrame | None = None,
) -> NfciPanel:
    ordered = tuple(sorted(bundle.observations, key=lambda row: (row.release_date, row.observation_week_end)))
    values = [row.nfci for row in ordered]
    spy_close = _close_series(spy_history)
    spy_return = spy_close.pct_change() * 100.0 if not spy_close.empty else pd.Series(dtype=float)
    spy_vol = (
        spy_close.pct_change().rolling(SPY_VOL_WINDOW_SESSIONS).std() * (252.0 ** 0.5)
        if not spy_close.empty
        else pd.Series(dtype=float)
    )
    if not ordered:
        coverage = _empty_nfci_coverage(bundle)
        return NfciPanel(
            recipe=nfci_recipe_manifest(),
            rows=(),
            source=bundle.source,
            nfci_count=bundle.nfci_count,
            history_weeks=0,
            coverage=coverage,
            abort_reasons=nfci_panel_abort_reasons((), coverage=coverage, nfci_count=bundle.nfci_count),
        )

    rows: list[NfciWeeklySnapshot] = []
    rising_streak = 0
    for index, observation in enumerate(ordered):
        d4w = None
        if index >= DELTA_WEEKS:
            prior = values[index - DELTA_WEEKS]
            d4w = observation.nfci - prior
        if d4w is None:
            rising_streak = 0
        elif d4w > 0:
            rising_streak += 1
        else:
            rising_streak = 0
        gate = evaluate_nfci_gate(
            nfci=observation.nfci,
            nfci_d4w=d4w,
            rising_streak=rising_streak,
        )
        release_stamp = pd.Timestamp(observation.release_date)
        rows.append(
            NfciWeeklySnapshot(
                observation_week_end=observation.observation_week_end,
                release_date=observation.release_date,
                nfci=observation.nfci,
                nfci_d4w=d4w,
                rising_streak=rising_streak,
                persistence_rising=rising_streak >= PERSISTENCE_WEEKS,
                spy_return_pct=_optional_float(spy_return.get(release_stamp)) if not spy_return.empty else None,
                spy_realized_vol_20d=_optional_float(spy_vol.get(release_stamp)) if not spy_vol.empty else None,
                gate=gate,
            )
        )
    coverage = summarize_nfci_coverage(rows, bundle=bundle)
    abort_reasons = nfci_panel_abort_reasons(rows, coverage=coverage, nfci_count=bundle.nfci_count)
    return NfciPanel(
        recipe=nfci_recipe_manifest(),
        rows=tuple(rows),
        source=bundle.source,
        nfci_count=bundle.nfci_count,
        history_weeks=len(rows),
        coverage=coverage,
        abort_reasons=abort_reasons,
    )


def build_hy_keep_panel(bundle: NfciSeriesBundle) -> HyKeepPanel:
    hy = _hy_series(bundle.hy_observations, "hy_oas")
    ig = _hy_series(bundle.hy_observations, "ig_oas")
    hy_count = sum(row.hy_oas is not None for row in bundle.hy_observations)
    ig_count = sum(row.ig_oas is not None for row in bundle.hy_observations)
    if hy.empty:
        reasons = ()
        if hy_count < HY_MIN_SERIES_SESSIONS_HARD:
            reasons = (
                f"{hy_count} KEEP HY OAS observations are available; "
                f"{HY_MIN_SERIES_SESSIONS_HARD} are required. Nested kill-switch vs HY "
                "OAS cannot be scored.",
            )
        return HyKeepPanel(
            recipe=hy_keep_recipe_manifest(),
            rows=(),
            hy_count=hy_count,
            ig_count=ig_count,
            abort_reasons=reasons,
        )

    d20 = hy.diff(HY_VELOCITY_WINDOW_SESSIONS) * 100.0
    d5 = hy.diff(HY_WEEKLY_WINDOW_SESSIONS) * 100.0
    gap = hy.subtract(ig) if not ig.empty else pd.Series(dtype=float)
    rows: list[HyKeepDailySnapshot] = []
    for stamp, hy_value in hy.items():
        as_of = pd.Timestamp(stamp).date()
        prior = hy.loc[hy.index < stamp].iloc[-HY_PERCENTILE_WINDOW_SESSIONS:]
        percentile_obs = int(prior.count())
        percentile = _percentile_of(float(hy_value), prior) if percentile_obs else None
        d20_bp = _optional_float(d20.get(stamp))
        gate = evaluate_hy_keep_gate(
            hy_oas=_optional_float(hy_value),
            hy_oas_d20_bp=d20_bp,
            hy_oas_percentile_252=percentile,
            percentile_observations=percentile_obs,
        )
        ig_value = _optional_float(ig.get(stamp)) if not ig.empty else None
        rows.append(
            HyKeepDailySnapshot(
                as_of=as_of,
                hy_oas=_optional_float(hy_value),
                ig_oas=ig_value,
                hy_ig_gap=_optional_float(gap.get(stamp)) if not gap.empty else None,
                hy_oas_d20_bp=d20_bp,
                hy_oas_d5_bp=_optional_float(d5.get(stamp)),
                hy_oas_percentile_252=percentile,
                percentile_observations=percentile_obs,
                gate=gate,
            )
        )
    abort_reasons = ()
    if hy_count < HY_MIN_SERIES_SESSIONS_HARD:
        abort_reasons = (
            f"{hy_count} KEEP HY OAS observations are available; "
            f"{HY_MIN_SERIES_SESSIONS_HARD} are required. Nested kill-switch vs HY "
            "OAS cannot be scored.",
        )
    return HyKeepPanel(
        recipe=hy_keep_recipe_manifest(),
        rows=tuple(rows),
        hy_count=hy_count,
        ig_count=ig_count,
        abort_reasons=abort_reasons,
    )


def summarize_nfci_coverage(
    rows: Sequence[NfciWeeklySnapshot],
    *,
    bundle: NfciSeriesBundle,
) -> dict[str, Any]:
    throttle_weeks = sum(row.gate.status == "throttle" for row in rows)
    full_weeks = sum(row.gate.status == "full" for row in rows)
    unknown_weeks = sum(row.gate.status == "unknown" for row in rows)
    delta_ready = sum(row.nfci_d4w is not None for row in rows)
    return {
        "nfci_count": bundle.nfci_count,
        "week_count": len(rows),
        "source": bundle.source,
        "first_release_date": bundle.first_release_date.isoformat() if bundle.first_release_date else None,
        "last_release_date": bundle.last_release_date.isoformat() if bundle.last_release_date else None,
        "gate_full_weeks": full_weeks,
        "gate_throttle_weeks": throttle_weeks,
        "gate_unknown_weeks": unknown_weeks,
        "delta_ready_weeks": delta_ready,
        "known_gate_share": None if not rows else round((full_weeks + throttle_weeks) / len(rows), 6),
        "meets_hard_minimum": bundle.nfci_count >= MIN_NFCI_WEEKS_HARD,
        "meets_recommended_minimum": bundle.nfci_count >= MIN_NFCI_WEEKS_RECOMMENDED,
        "join_on": "release_date",
    }


def nfci_panel_abort_reasons(
    rows: Sequence[NfciWeeklySnapshot],
    *,
    coverage: Mapping[str, Any],
    nfci_count: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if nfci_count < MIN_NFCI_WEEKS_HARD:
        reasons.append(
            f"{nfci_count} NFCI weekly observations are available; "
            f"{MIN_NFCI_WEEKS_HARD} are required. FAIL data-blocked."
        )
    if not rows:
        reasons.append("The release-dated NFCI panel is empty.")
    delta_ready = int(coverage.get("delta_ready_weeks") or 0)
    if rows and delta_ready < DELTA_WEEKS + PERSISTENCE_WEEKS:
        reasons.append(
            f"Only {delta_ready} weeks have a 4-week NFCI change; "
            f"{DELTA_WEEKS + PERSISTENCE_WEEKS} are required for the frozen persistence rule."
        )
    return tuple(reasons)


def build_nfci_regime_view(panel: NfciPanel) -> NfciRegimeView:
    latest = panel.rows[-1] if panel.rows else None
    warnings = list(panel.abort_reasons)
    if latest is None:
        return NfciRegimeView(
            mode=NFCI_MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            recipe_version=NFCI_RECIPE_VERSION,
            as_of_date=None,
            snapshot=None,
            gate=evaluate_nfci_gate(nfci=None, nfci_d4w=None, rising_streak=0).to_dict(),
            summary="NFCI regime metrics are unavailable.",
            warnings=warnings,
            updated_at=datetime.now(UTC).isoformat(),
        )
    coverage_score = int(
        round(
            min(
                100.0,
                100.0
                * (
                    (1.0 if latest.nfci is not None else 0.0) * 0.5
                    + (1.0 if latest.nfci_d4w is not None else 0.0) * 0.3
                    + (1.0 if latest.rising_streak >= PERSISTENCE_WEEKS or latest.gate.status == "full" else 0.0) * 0.2
                ),
            )
        )
    )
    gate_status = latest.gate.status
    match gate_status:
        case "full":
            summary = (
                "NFCI regime is full-risk-on on the frozen persistence throttle. "
                "This does not change live recommendations."
            )
            status = "constructive"
        case "throttle":
            summary = (
                "NFCI regime throttles long-screen aggressiveness on the frozen "
                "rising-persistence rule. This does not change live recommendations."
            )
            status = "cautious"
        case "unknown":
            summary = (
                "NFCI regime cannot be read because level or 4-week change is missing "
                "on the release-dated panel."
            )
            status = "unavailable"
        case _ as unreachable:
            assert_never(unreachable)
    evidence = [
        f"Observation week-end: {latest.observation_week_end.isoformat()}.",
        f"Release date used for joins: {latest.release_date.isoformat()}.",
        f"NFCI level: {_fmt(latest.nfci)}.",
        f"4-week Δ: {_fmt(latest.nfci_d4w)}.",
        f"Rising streak: {latest.rising_streak} week(s) (frozen N={PERSISTENCE_WEEKS}).",
        f"Frozen gate is {gate_status_label(gate_status)}.",
    ]
    return NfciRegimeView(
        mode=NFCI_MODE,
        status=status,
        applied_impact=0,
        coverage_score=coverage_score,
        recipe_version=NFCI_RECIPE_VERSION,
        as_of_date=latest.release_date.isoformat(),
        snapshot=latest.to_dict(),
        gate=latest.gate.to_dict(),
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings + list(latest.gate.reasons))),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _hy_series(observations: Sequence[HyKeepObservation], field_name: str) -> pd.Series:
    points = {
        pd.Timestamp(row.as_of): getattr(row, field_name)
        for row in observations
        if getattr(row, field_name) is not None
    }
    if not points:
        return pd.Series(dtype=float)
    series = pd.Series(points, dtype=float).sort_index()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


def _close_series(history: pd.DataFrame | None) -> pd.Series:
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    series = pd.to_numeric(history["Close"], errors="coerce").dropna().sort_index()
    if series.empty:
        return pd.Series(dtype=float)
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series


def _percentile_of(current: float, prior: pd.Series) -> float | None:
    values = pd.to_numeric(prior, errors="coerce").dropna()
    if len(values) < HY_PERCENTILE_MIN_OBSERVATIONS:
        return None
    return round(float((values < current).mean() * 100.0), 6)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        return None
    number = float(value)
    if number != number:
        return None
    return number


def _fmt(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}{suffix}"


def _empty_nfci_coverage(bundle: NfciSeriesBundle) -> dict[str, Any]:
    return {
        "nfci_count": bundle.nfci_count,
        "week_count": 0,
        "source": bundle.source,
        "first_release_date": None,
        "last_release_date": None,
        "gate_full_weeks": 0,
        "gate_throttle_weeks": 0,
        "gate_unknown_weeks": 0,
        "delta_ready_weeks": 0,
        "known_gate_share": None,
        "meets_hard_minimum": False,
        "meets_recommended_minimum": False,
        "join_on": "release_date",
    }


__all__ = [
    "GateStatus",
    "HyKeepDailySnapshot",
    "HyKeepGateDecision",
    "HyKeepPanel",
    "NfciGateDecision",
    "NfciPanel",
    "NfciRegimeView",
    "NfciWeeklySnapshot",
    "build_hy_keep_panel",
    "build_nfci_panel",
    "build_nfci_regime_view",
    "evaluate_hy_keep_gate",
    "evaluate_nfci_gate",
    "gate_status_label",
    "nfci_panel_abort_reasons",
    "summarize_nfci_coverage",
]
