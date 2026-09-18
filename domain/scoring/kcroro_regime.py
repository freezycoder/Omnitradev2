from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import pandas as pd

from config.kcroro_regime import (
    HY_KEEP_RECIPE_VERSION,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_PERCENTILE_MIN_OBSERVATIONS,
    HY_PERCENTILE_THROTTLE,
    HY_PERCENTILE_WINDOW_SESSIONS,
    HY_VELOCITY_WIDENING_BP,
    HY_VELOCITY_WINDOW_SESSIONS,
    HY_WEEKLY_WINDOW_SESSIONS,
    ICE_REDISTRIBUTION_NOTICE,
    KCRORO_CITATION,
    KCRORO_MODE,
    KCRORO_RECIPE_VERSION,
    LEVEL_THROTTLE,
    MIN_KCRORO_SESSIONS_HARD,
    MIN_KCRORO_SESSIONS_RECOMMENDED,
    MIN_NFCI_WEEKS_HARD,
    NFCI_DELTA_WEEKS,
    NFCI_KEEP_RECIPE_VERSION,
    NFCI_PERSISTENCE_WEEKS,
    SHOCK_SUM_THROTTLE,
    SHOCK_SUM_WINDOW_SESSIONS,
    SPY_VOL_WINDOW_SESSIONS,
    THROTTLE_WEIGHT,
    hy_keep_recipe_manifest,
    kcroro_recipe_manifest,
    nfci_keep_recipe_manifest,
)
from providers.macro.kcroro_client import HyKeepObservation, KcroroSeriesBundle


GateStatus = Literal["full", "throttle", "unknown"]


@dataclass(frozen=True)
class KcroroGateDecision:
    status: GateStatus
    kcroro: float | None
    shock_sum_20d: float | None
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = KCRORO_RECIPE_VERSION

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
class NfciKeepGateDecision:
    status: GateStatus
    nfci: float | None
    nfci_d4w: float | None
    rising_streak: int
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = NFCI_KEEP_RECIPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class KcroroDailySnapshot:
    observation_date: date
    release_date: date
    kcroro: float | None
    shock_sum_20d: float | None
    spreads: float | None
    equities: float | None
    liquidity: float | None
    fx_gold: float | None
    non_equity: float | None
    non_equity_shock_sum_20d: float | None
    spy_return_pct: float | None
    spy_realized_vol_20d: float | None
    vix_level: float | None
    gate: KcroroGateDecision
    ablation_gate: KcroroGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observation_date"] = self.observation_date.isoformat()
        payload["release_date"] = self.release_date.isoformat()
        payload["gate"] = self.gate.to_dict()
        payload["ablation_gate"] = self.ablation_gate.to_dict()
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
class NfciKeepWeeklySnapshot:
    observation_week_end: date
    release_date: date
    nfci: float | None
    nfci_d4w: float | None
    rising_streak: int
    persistence_rising: bool
    gate: NfciKeepGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observation_week_end"] = self.observation_week_end.isoformat()
        payload["release_date"] = self.release_date.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class KcroroRegimeView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    recipe_version: str
    as_of_date: str | None
    snapshot: dict[str, Any] | None
    gate: dict[str, Any]
    summary: str
    citation: str = KCRORO_CITATION
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class KcroroPanel:
    recipe: dict[str, Any]
    rows: tuple[KcroroDailySnapshot, ...]
    source: str
    kcroro_count: int
    history_sessions: int
    coverage: dict[str, Any]
    abort_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "source": self.source,
            "kcroro_count": self.kcroro_count,
            "history_sessions": self.history_sessions,
            "coverage": self.coverage,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
            "citation": KCRORO_CITATION,
        }

    def snapshot_on(self, as_of: date) -> KcroroDailySnapshot | None:
        """Latest print whose release_date is on or before as_of. No observation look-ahead."""
        chosen: KcroroDailySnapshot | None = None
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


@dataclass(frozen=True)
class NfciKeepPanel:
    recipe: dict[str, Any]
    rows: tuple[NfciKeepWeeklySnapshot, ...]
    nfci_count: int
    abort_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "nfci_count": self.nfci_count,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> NfciKeepWeeklySnapshot | None:
        chosen: NfciKeepWeeklySnapshot | None = None
        for row in self.rows:
            if row.release_date <= as_of:
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


def evaluate_kcroro_gate(
    *,
    kcroro: float | None,
    shock_sum_20d: float | None,
    label: str = "KCRORO",
) -> KcroroGateDecision:
    reasons: list[str] = []
    if kcroro is None or shock_sum_20d is None:
        reasons.append(f"{label} level or 20-session shock sum is missing on the release-dated panel.")
        return KcroroGateDecision(
            status="unknown",
            kcroro=kcroro,
            shock_sum_20d=shock_sum_20d,
            throttle_weight=None,
            reasons=tuple(reasons),
        )
    level_hit = kcroro > LEVEL_THROTTLE
    sum_hit = shock_sum_20d > SHOCK_SUM_THROTTLE
    if level_hit:
        reasons.append(
            f"{label} is {kcroro:.4f}, above the frozen {LEVEL_THROTTLE:g} risk-off threshold "
            "(positive ≈ risk-off)."
        )
    if sum_hit:
        reasons.append(
            f"Causal {SHOCK_SUM_WINDOW_SESSIONS}-session {label} shock sum is {shock_sum_20d:.4f}, "
            f"above the frozen {SHOCK_SUM_THROTTLE:g} threshold."
        )
    if level_hit or sum_hit:
        reasons.append(
            f"Long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
        return KcroroGateDecision(
            status="throttle",
            kcroro=kcroro,
            shock_sum_20d=shock_sum_20d,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=tuple(reasons),
        )
    reasons.append(
        f"{label} is {kcroro:.4f} with 20-session shock sum {shock_sum_20d:.4f}; "
        "the frozen throttle is not engaged."
    )
    return KcroroGateDecision(
        status="full",
        kcroro=kcroro,
        shock_sum_20d=shock_sum_20d,
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


def evaluate_nfci_keep_gate(
    *,
    nfci: float | None,
    nfci_d4w: float | None,
    rising_streak: int,
) -> NfciKeepGateDecision:
    reasons: list[str] = []
    if nfci is None or nfci_d4w is None:
        reasons.append("NFCI level or 4-week change is missing on the release-dated panel.")
        return NfciKeepGateDecision(
            status="unknown",
            nfci=nfci,
            nfci_d4w=nfci_d4w,
            rising_streak=rising_streak,
            throttle_weight=None,
            reasons=tuple(reasons),
        )
    if rising_streak >= NFCI_PERSISTENCE_WEEKS:
        reasons.append(
            f"NFCI 4-week change is {nfci_d4w:.3f} and has been strictly positive for "
            f"{rising_streak} consecutive weekly prints (KEEP N={NFCI_PERSISTENCE_WEEKS})."
        )
        reasons.append(
            f"KEEP long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
        return NfciKeepGateDecision(
            status="throttle",
            nfci=nfci,
            nfci_d4w=nfci_d4w,
            rising_streak=rising_streak,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=tuple(reasons),
        )
    reasons.append(
        f"NFCI level is {nfci:.3f} with 4-week Δ {nfci_d4w:.3f} and a rising streak of "
        f"{rising_streak} (need {NFCI_PERSISTENCE_WEEKS}). The KEEP throttle is not engaged."
    )
    return NfciKeepGateDecision(
        status="full",
        nfci=nfci,
        nfci_d4w=nfci_d4w,
        rising_streak=rising_streak,
        throttle_weight=1.0,
        reasons=tuple(reasons),
    )


def build_kcroro_panel(
    bundle: KcroroSeriesBundle,
    *,
    spy_history: pd.DataFrame | None = None,
    vix_history: pd.DataFrame | None = None,
) -> KcroroPanel:
    ordered = tuple(sorted(bundle.observations, key=lambda row: (row.release_date, row.observation_date)))
    values = [row.kcroro for row in ordered]
    non_equity_values = [_non_equity_mean(row.spreads, row.liquidity, row.fx_gold) for row in ordered]
    spy_close = _close_series(spy_history)
    spy_return = spy_close.pct_change() * 100.0 if not spy_close.empty else pd.Series(dtype=float)
    spy_vol = (
        spy_close.pct_change().rolling(SPY_VOL_WINDOW_SESSIONS).std() * (252.0 ** 0.5)
        if not spy_close.empty
        else pd.Series(dtype=float)
    )
    vix_close = _close_series(vix_history)
    if not ordered:
        coverage = _empty_kcroro_coverage(bundle)
        return KcroroPanel(
            recipe=kcroro_recipe_manifest(),
            rows=(),
            source=bundle.source,
            kcroro_count=bundle.kcroro_count,
            history_sessions=0,
            coverage=coverage,
            abort_reasons=kcroro_panel_abort_reasons((), coverage=coverage, kcroro_count=bundle.kcroro_count),
        )

    rows: list[KcroroDailySnapshot] = []
    for index, observation in enumerate(ordered):
        shock_sum = None
        if index + 1 >= SHOCK_SUM_WINDOW_SESSIONS:
            shock_sum = float(sum(values[index + 1 - SHOCK_SUM_WINDOW_SESSIONS : index + 1]))
        non_equity = non_equity_values[index]
        non_equity_sum = None
        if index + 1 >= SHOCK_SUM_WINDOW_SESSIONS:
            window = non_equity_values[index + 1 - SHOCK_SUM_WINDOW_SESSIONS : index + 1]
            if all(item is not None for item in window):
                non_equity_sum = float(sum(item for item in window if item is not None))
        gate = evaluate_kcroro_gate(kcroro=observation.kcroro, shock_sum_20d=shock_sum)
        ablation_gate = evaluate_kcroro_gate(
            kcroro=non_equity,
            shock_sum_20d=non_equity_sum,
            label="non-equity RORO (spreads/funding/FX-gold)",
        )
        release_stamp = pd.Timestamp(observation.release_date)
        rows.append(
            KcroroDailySnapshot(
                observation_date=observation.observation_date,
                release_date=observation.release_date,
                kcroro=observation.kcroro,
                shock_sum_20d=shock_sum,
                spreads=observation.spreads,
                equities=observation.equities,
                liquidity=observation.liquidity,
                fx_gold=observation.fx_gold,
                non_equity=non_equity,
                non_equity_shock_sum_20d=non_equity_sum,
                spy_return_pct=_optional_float(spy_return.get(release_stamp)) if not spy_return.empty else None,
                spy_realized_vol_20d=_optional_float(spy_vol.get(release_stamp)) if not spy_vol.empty else None,
                vix_level=_optional_float(vix_close.get(release_stamp)) if not vix_close.empty else None,
                gate=gate,
                ablation_gate=ablation_gate,
            )
        )
    coverage = summarize_kcroro_coverage(rows, bundle=bundle)
    abort_reasons = kcroro_panel_abort_reasons(rows, coverage=coverage, kcroro_count=bundle.kcroro_count)
    return KcroroPanel(
        recipe=kcroro_recipe_manifest(),
        rows=tuple(rows),
        source=bundle.source,
        kcroro_count=bundle.kcroro_count,
        history_sessions=len(rows),
        coverage=coverage,
        abort_reasons=abort_reasons,
    )


def build_hy_keep_panel(bundle: KcroroSeriesBundle) -> HyKeepPanel:
    hy = _named_series(bundle.hy_observations, "hy_oas")
    ig = _named_series(bundle.hy_observations, "ig_oas")
    hy_count = sum(row.hy_oas is not None for row in bundle.hy_observations)
    ig_count = sum(row.ig_oas is not None for row in bundle.hy_observations)
    if hy.empty:
        reasons = ()
        if hy_count < HY_MIN_SERIES_SESSIONS_HARD:
            reasons = (
                f"{hy_count} KEEP HY OAS observations are available; "
                f"{HY_MIN_SERIES_SESSIONS_HARD} are required. Nested kill-switch vs HY "
                "OAS + NFCI cannot be scored.",
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
            "OAS + NFCI cannot be scored.",
        )
    return HyKeepPanel(
        recipe=hy_keep_recipe_manifest(),
        rows=tuple(rows),
        hy_count=hy_count,
        ig_count=ig_count,
        abort_reasons=abort_reasons,
    )


def build_nfci_keep_panel(bundle: KcroroSeriesBundle) -> NfciKeepPanel:
    ordered = tuple(
        sorted(bundle.nfci_observations, key=lambda row: (row.release_date, row.observation_week_end))
    )
    values = [row.nfci for row in ordered]
    nfci_count = bundle.nfci_count
    if not ordered:
        reasons = ()
        if nfci_count < MIN_NFCI_WEEKS_HARD:
            reasons = (
                f"{nfci_count} KEEP NFCI weekly observations are available; "
                f"{MIN_NFCI_WEEKS_HARD} are required. Nested kill-switch vs HY OAS + "
                "NFCI cannot be scored.",
            )
        return NfciKeepPanel(
            recipe=nfci_keep_recipe_manifest(),
            rows=(),
            nfci_count=nfci_count,
            abort_reasons=reasons,
        )

    rows: list[NfciKeepWeeklySnapshot] = []
    rising_streak = 0
    for index, observation in enumerate(ordered):
        d4w = None
        if index >= NFCI_DELTA_WEEKS:
            prior = values[index - NFCI_DELTA_WEEKS]
            d4w = observation.nfci - prior
        if d4w is None:
            rising_streak = 0
        elif d4w > 0:
            rising_streak += 1
        else:
            rising_streak = 0
        gate = evaluate_nfci_keep_gate(
            nfci=observation.nfci,
            nfci_d4w=d4w,
            rising_streak=rising_streak,
        )
        rows.append(
            NfciKeepWeeklySnapshot(
                observation_week_end=observation.observation_week_end,
                release_date=observation.release_date,
                nfci=observation.nfci,
                nfci_d4w=d4w,
                rising_streak=rising_streak,
                persistence_rising=rising_streak >= NFCI_PERSISTENCE_WEEKS,
                gate=gate,
            )
        )
    abort_reasons = ()
    if nfci_count < MIN_NFCI_WEEKS_HARD:
        abort_reasons = (
            f"{nfci_count} KEEP NFCI weekly observations are available; "
            f"{MIN_NFCI_WEEKS_HARD} are required. Nested kill-switch vs HY OAS + "
            "NFCI cannot be scored.",
        )
    return NfciKeepPanel(
        recipe=nfci_keep_recipe_manifest(),
        rows=tuple(rows),
        nfci_count=nfci_count,
        abort_reasons=abort_reasons,
    )


def summarize_kcroro_coverage(
    rows: Sequence[KcroroDailySnapshot],
    *,
    bundle: KcroroSeriesBundle,
) -> dict[str, Any]:
    throttle_days = sum(row.gate.status == "throttle" for row in rows)
    full_days = sum(row.gate.status == "full" for row in rows)
    unknown_days = sum(row.gate.status == "unknown" for row in rows)
    shock_ready = sum(row.shock_sum_20d is not None for row in rows)
    ablation_known = sum(row.ablation_gate.status != "unknown" for row in rows)
    return {
        "kcroro_count": bundle.kcroro_count,
        "session_count": len(rows),
        "source": bundle.source,
        "first_release_date": bundle.first_release_date.isoformat() if bundle.first_release_date else None,
        "last_release_date": bundle.last_release_date.isoformat() if bundle.last_release_date else None,
        "gate_full_days": full_days,
        "gate_throttle_days": throttle_days,
        "gate_unknown_days": unknown_days,
        "shock_sum_ready_days": shock_ready,
        "ablation_known_days": ablation_known,
        "spreads_count": bundle.spreads_count,
        "equities_count": bundle.equities_count,
        "liquidity_count": bundle.liquidity_count,
        "fx_gold_count": bundle.fx_gold_count,
        "known_gate_share": None if not rows else round((full_days + throttle_days) / len(rows), 6),
        "meets_hard_minimum": bundle.kcroro_count >= MIN_KCRORO_SESSIONS_HARD,
        "meets_recommended_minimum": bundle.kcroro_count >= MIN_KCRORO_SESSIONS_RECOMMENDED,
        "join_on": "release_date",
    }


def kcroro_panel_abort_reasons(
    rows: Sequence[KcroroDailySnapshot],
    *,
    coverage: Mapping[str, Any],
    kcroro_count: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if kcroro_count < MIN_KCRORO_SESSIONS_HARD:
        reasons.append(
            f"{kcroro_count} KCRORO daily observations are available; "
            f"{MIN_KCRORO_SESSIONS_HARD} are required. FAIL data-blocked."
        )
    if not rows:
        reasons.append("The release-dated KCRORO panel is empty.")
    shock_ready = int(coverage.get("shock_sum_ready_days") or 0)
    if rows and shock_ready < SHOCK_SUM_WINDOW_SESSIONS:
        reasons.append(
            f"Only {shock_ready} sessions have a 20-session KCRORO shock sum; "
            f"{SHOCK_SUM_WINDOW_SESSIONS} are required for the frozen throttle."
        )
    return tuple(reasons)


def build_kcroro_regime_view(panel: KcroroPanel) -> KcroroRegimeView:
    latest = panel.rows[-1] if panel.rows else None
    warnings = list(panel.abort_reasons)
    if latest is None:
        return KcroroRegimeView(
            mode=KCRORO_MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            recipe_version=KCRORO_RECIPE_VERSION,
            as_of_date=None,
            snapshot=None,
            gate=evaluate_kcroro_gate(kcroro=None, shock_sum_20d=None).to_dict(),
            summary="KCRORO regime metrics are unavailable.",
            warnings=warnings,
            updated_at=datetime.now(UTC).isoformat(),
        )
    coverage_score = int(
        round(
            min(
                100.0,
                100.0
                * (
                    (1.0 if latest.kcroro is not None else 0.0) * 0.5
                    + (1.0 if latest.shock_sum_20d is not None else 0.0) * 0.3
                    + (1.0 if latest.gate.status != "unknown" else 0.0) * 0.2
                ),
            )
        )
    )
    gate_status = latest.gate.status
    match gate_status:
        case "full":
            summary = (
                "KCRORO regime is full-risk-on on the frozen level/shock-sum throttle. "
                "This does not change live recommendations."
            )
            status = "constructive"
        case "throttle":
            summary = (
                "KCRORO regime throttles long-screen aggressiveness on the frozen "
                "positive-print or 20-session shock-sum rule. This does not change live "
                "recommendations."
            )
            status = "cautious"
        case "unknown":
            summary = (
                "KCRORO regime cannot be read because level or 20-session shock sum is "
                "missing on the release-dated panel."
            )
            status = "unavailable"
        case _ as unreachable:
            assert_never(unreachable)
    evidence = [
        f"Observation date: {latest.observation_date.isoformat()}.",
        f"Release date used for joins: {latest.release_date.isoformat()}.",
        f"KCRORO level: {_fmt(latest.kcroro)} (positive ≈ risk-off).",
        f"20-session shock sum: {_fmt(latest.shock_sum_20d)}.",
        f"Frozen gate is {gate_status_label(gate_status)}.",
        f"Equity-leg ablation gate is {gate_status_label(latest.ablation_gate.status)}.",
        KCRORO_CITATION,
    ]
    return KcroroRegimeView(
        mode=KCRORO_MODE,
        status=status,
        applied_impact=0,
        coverage_score=coverage_score,
        recipe_version=KCRORO_RECIPE_VERSION,
        as_of_date=latest.release_date.isoformat(),
        snapshot=latest.to_dict(),
        gate=latest.gate.to_dict(),
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings + list(latest.gate.reasons))),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _non_equity_mean(
    spreads: float | None,
    liquidity: float | None,
    fx_gold: float | None,
) -> float | None:
    if spreads is None or liquidity is None or fx_gold is None:
        return None
    return (spreads + liquidity + fx_gold) / 3.0


def _named_series(observations: Sequence[HyKeepObservation], field_name: str) -> pd.Series:
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
    return f"{value:.4f}{suffix}"


def _empty_kcroro_coverage(bundle: KcroroSeriesBundle) -> dict[str, Any]:
    return {
        "kcroro_count": bundle.kcroro_count,
        "session_count": 0,
        "source": bundle.source,
        "first_release_date": None,
        "last_release_date": None,
        "gate_full_days": 0,
        "gate_throttle_days": 0,
        "gate_unknown_days": 0,
        "shock_sum_ready_days": 0,
        "ablation_known_days": 0,
        "spreads_count": bundle.spreads_count,
        "equities_count": bundle.equities_count,
        "liquidity_count": bundle.liquidity_count,
        "fx_gold_count": bundle.fx_gold_count,
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
    "KcroroDailySnapshot",
    "KcroroGateDecision",
    "KcroroPanel",
    "KcroroRegimeView",
    "NfciKeepGateDecision",
    "NfciKeepPanel",
    "NfciKeepWeeklySnapshot",
    "build_hy_keep_panel",
    "build_kcroro_panel",
    "build_kcroro_regime_view",
    "build_nfci_keep_panel",
    "evaluate_hy_keep_gate",
    "evaluate_kcroro_gate",
    "evaluate_nfci_keep_gate",
    "gate_status_label",
    "kcroro_panel_abort_reasons",
    "summarize_kcroro_coverage",
]
