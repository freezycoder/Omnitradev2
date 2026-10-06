from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import pandas as pd

from config.stfm_funding_liquidity import (
    DAILY_RATE_MNEMONICS,
    DAILY_VOLUME_MNEMONICS,
    HY_KEEP_RECIPE_VERSION,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_PERCENTILE_MIN_OBSERVATIONS,
    HY_PERCENTILE_THROTTLE,
    HY_PERCENTILE_WINDOW_SESSIONS,
    HY_VELOCITY_WIDENING_BP,
    HY_VELOCITY_WINDOW_SESSIONS,
    HY_WEEKLY_WINDOW_SESSIONS,
    ICE_REDISTRIBUTION_NOTICE,
    MIN_MMF_MONTHS_HARD,
    MIN_NFCI_WEEKS_HARD,
    MIN_STFM_SESSIONS_HARD,
    MMF_ZSCORE_MIN_OBSERVATIONS,
    MMF_ZSCORE_WINDOW_MONTHS,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_EFFR,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    NFCI_DELTA_WEEKS,
    NFCI_KEEP_RECIPE_VERSION,
    NFCI_PERSISTENCE_WEEKS,
    RORO_INGEST_V1,
    SOFR_EFFR_DELTA_SESSIONS,
    SOFR_EFFR_WIDEN_BP,
    SPY_VOL_WINDOW_SESSIONS,
    STFM_MODE,
    STFM_RECIPE_VERSION,
    THROTTLE_WEIGHT,
    VOLUME_DELTA_LONG_SESSIONS,
    VOLUME_DELTA_SHORT_SESSIONS,
    VOLUME_ZSCORE_DROP,
    ZSCORE_MIN_OBSERVATIONS,
    ZSCORE_WINDOW_SESSIONS,
    hy_keep_recipe_manifest,
    nfci_keep_recipe_manifest,
    stfm_recipe_manifest,
)
from providers.macro.ofr_stfm_client import (
    HyKeepObservation,
    NfciKeepObservation,
    OfrPoint,
    StfmSeriesBundle,
)


GateStatus = Literal["full", "throttle", "unknown"]


@dataclass(frozen=True)
class StfmGateDecision:
    status: GateStatus
    volume_drop: bool | None
    spread_widen: bool | None
    dvp_z: float | None
    gcf_z: float | None
    sofr_effr_d5_bp: float | None
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = STFM_RECIPE_VERSION
    control: str = "full_pack"

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
class StfmDailySnapshot:
    observation_date: date
    release_date: date
    dvp_volume: float | None
    gcf_volume: float | None
    dvp_z: float | None
    gcf_z: float | None
    dvp_d5_pct: float | None
    dvp_d20_pct: float | None
    gcf_d5_pct: float | None
    gcf_d20_pct: float | None
    mmf_total: float | None
    mmf_z: float | None
    mmf_d1m_pct: float | None
    sofr: float | None
    effr: float | None
    sofr_effr_spread_bp: float | None
    sofr_effr_d5_bp: float | None
    spy_return_pct: float | None
    spy_realized_vol_20d: float | None
    full_pack_gate: StfmGateDecision
    sofr_only_gate: StfmGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observation_date"] = self.observation_date.isoformat()
        payload["release_date"] = self.release_date.isoformat()
        payload["full_pack_gate"] = self.full_pack_gate.to_dict()
        payload["sofr_only_gate"] = self.sofr_only_gate.to_dict()
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
    gate: NfciKeepGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observation_week_end"] = self.observation_week_end.isoformat()
        payload["release_date"] = self.release_date.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class StfmRegimeView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    recipe_version: str
    as_of_date: str | None
    snapshot: dict[str, Any] | None
    gate: dict[str, Any]
    sofr_only_gate: dict[str, Any]
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StfmPanel:
    recipe: dict[str, Any]
    rows: tuple[StfmDailySnapshot, ...]
    source: str
    coverage: dict[str, Any]
    abort_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "source": self.source,
            "coverage": self.coverage,
            "abort_reasons": list(self.abort_reasons),
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> StfmDailySnapshot | None:
        chosen: StfmDailySnapshot | None = None
        for row in self.rows:
            if row.release_date <= as_of:
                chosen = row
            elif chosen is not None:
                break
        return chosen


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


def evaluate_stfm_full_pack_gate(
    *,
    dvp_z: float | None,
    gcf_z: float | None,
    sofr_effr_d5_bp: float | None,
) -> StfmGateDecision:
    reasons: list[str] = []
    volume_drop: bool | None
    if dvp_z is None and gcf_z is None:
        volume_drop = None
        reasons.append("DVP and GCF causal z-scores are missing. Null OFR prints are not zero-filled.")
    else:
        volume_drop = (dvp_z is not None and dvp_z <= VOLUME_ZSCORE_DROP) or (
            gcf_z is not None and gcf_z <= VOLUME_ZSCORE_DROP
        )
    spread_widen: bool | None
    if sofr_effr_d5_bp is None:
        spread_widen = None
        reasons.append("5-session SOFR-EFFR change is missing.")
    else:
        spread_widen = sofr_effr_d5_bp > SOFR_EFFR_WIDEN_BP
    if volume_drop is None or spread_widen is None:
        return StfmGateDecision(
            status="unknown",
            volume_drop=volume_drop,
            spread_widen=spread_widen,
            dvp_z=dvp_z,
            gcf_z=gcf_z,
            sofr_effr_d5_bp=sofr_effr_d5_bp,
            throttle_weight=None,
            reasons=tuple(reasons),
            control="full_pack",
        )
    if volume_drop and spread_widen:
        reasons.append(
            f"Joint funding-stress flag: volume z-score drop "
            f"(DVP {_fmt(dvp_z)}, GCF {_fmt(gcf_z)}; threshold {VOLUME_ZSCORE_DROP:.1f}) "
            f"and SOFR-EFFR 5-session change {_fmt(sofr_effr_d5_bp, suffix=' bp')} "
            f"(threshold {SOFR_EFFR_WIDEN_BP:.0f} bp)."
        )
        reasons.append(
            f"Long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
        return StfmGateDecision(
            status="throttle",
            volume_drop=True,
            spread_widen=True,
            dvp_z=dvp_z,
            gcf_z=gcf_z,
            sofr_effr_d5_bp=sofr_effr_d5_bp,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=tuple(reasons),
            control="full_pack",
        )
    reasons.append(
        "Frozen joint volume-drop + spread-widen flag is not engaged "
        f"(volume_drop={volume_drop}, spread_widen={spread_widen})."
    )
    return StfmGateDecision(
        status="full",
        volume_drop=volume_drop,
        spread_widen=spread_widen,
        dvp_z=dvp_z,
        gcf_z=gcf_z,
        sofr_effr_d5_bp=sofr_effr_d5_bp,
        throttle_weight=1.0,
        reasons=tuple(reasons),
        control="full_pack",
    )


def evaluate_sofr_only_gate(*, sofr_effr_d5_bp: float | None) -> StfmGateDecision:
    if sofr_effr_d5_bp is None:
        return StfmGateDecision(
            status="unknown",
            volume_drop=None,
            spread_widen=None,
            dvp_z=None,
            gcf_z=None,
            sofr_effr_d5_bp=None,
            throttle_weight=None,
            reasons=("5-session SOFR-EFFR change is missing for the SOFR-only control.",),
            control="sofr_only",
        )
    spread_widen = sofr_effr_d5_bp > SOFR_EFFR_WIDEN_BP
    if spread_widen:
        return StfmGateDecision(
            status="throttle",
            volume_drop=None,
            spread_widen=True,
            dvp_z=None,
            gcf_z=None,
            sofr_effr_d5_bp=sofr_effr_d5_bp,
            throttle_weight=THROTTLE_WEIGHT,
            reasons=(
                f"SOFR-only control: 5-session SOFR-EFFR change is {sofr_effr_d5_bp:.1f} bp, "
                f"above {SOFR_EFFR_WIDEN_BP:.0f} bp. Volumes and MMF are excluded.",
            ),
            control="sofr_only",
        )
    return StfmGateDecision(
        status="full",
        volume_drop=None,
        spread_widen=False,
        dvp_z=None,
        gcf_z=None,
        sofr_effr_d5_bp=sofr_effr_d5_bp,
        throttle_weight=1.0,
        reasons=(
            f"SOFR-only control is full; 5-session SOFR-EFFR change is {sofr_effr_d5_bp:.1f} bp.",
        ),
        control="sofr_only",
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
            f"{rising_streak} consecutive weekly prints (frozen N={NFCI_PERSISTENCE_WEEKS})."
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
        f"{rising_streak} (need {NFCI_PERSISTENCE_WEEKS}). The frozen throttle is not engaged."
    )
    return NfciKeepGateDecision(
        status="full",
        nfci=nfci,
        nfci_d4w=nfci_d4w,
        rising_streak=rising_streak,
        throttle_weight=1.0,
        reasons=tuple(reasons),
    )


def build_stfm_panel(
    bundle: StfmSeriesBundle,
    *,
    spy_history: pd.DataFrame | None = None,
) -> StfmPanel:
    dvp = _ofr_series(bundle.series.get(MNEMONIC_DVP_VOLUME, ()))
    gcf = _ofr_series(bundle.series.get(MNEMONIC_GCF_VOLUME, ()))
    sofr = _ofr_series(bundle.series.get(MNEMONIC_SOFR, ()))
    effr = _ofr_series(bundle.series.get(MNEMONIC_EFFR, ()))
    mmf = _ofr_series(bundle.series.get(MNEMONIC_MMF_TOTAL, ()))
    observation_by_release = _observation_by_release(bundle)
    index = _union_index((dvp, gcf, sofr, effr))
    spy_close = _close_series(spy_history)
    spy_return = spy_close.pct_change() * 100.0 if not spy_close.empty else pd.Series(dtype=float)
    spy_vol = (
        spy_close.pct_change().rolling(SPY_VOL_WINDOW_SESSIONS).std() * (252.0 ** 0.5)
        if not spy_close.empty
        else pd.Series(dtype=float)
    )
    if index.empty:
        coverage = _empty_stfm_coverage(bundle)
        return StfmPanel(
            recipe=stfm_recipe_manifest(),
            rows=(),
            source=bundle.source,
            coverage=coverage,
            abort_reasons=stfm_panel_abort_reasons((), coverage=coverage, bundle=bundle),
        )

    dvp_z = _causal_zscore(dvp, window=ZSCORE_WINDOW_SESSIONS, min_obs=ZSCORE_MIN_OBSERVATIONS)
    gcf_z = _causal_zscore(gcf, window=ZSCORE_WINDOW_SESSIONS, min_obs=ZSCORE_MIN_OBSERVATIONS)
    mmf_z_monthly = _causal_zscore(
        mmf,
        window=MMF_ZSCORE_WINDOW_MONTHS,
        min_obs=MMF_ZSCORE_MIN_OBSERVATIONS,
    )
    mmf_d1m = _percent_change(mmf, 1)
    spread = _spread_bp(sofr, effr)
    spread_d5_series = _change(spread, SOFR_EFFR_DELTA_SESSIONS)
    dvp_d5 = _percent_change(dvp, VOLUME_DELTA_SHORT_SESSIONS)
    dvp_d20 = _percent_change(dvp, VOLUME_DELTA_LONG_SESSIONS)
    gcf_d5 = _percent_change(gcf, VOLUME_DELTA_SHORT_SESSIONS)
    gcf_d20 = _percent_change(gcf, VOLUME_DELTA_LONG_SESSIONS)
    rows: list[StfmDailySnapshot] = []
    for stamp in index:
        release_date = pd.Timestamp(stamp).date()
        observation_date = observation_by_release.get(release_date, release_date)
        dvp_value = _optional_float(dvp.get(stamp))
        gcf_value = _optional_float(gcf.get(stamp))
        dvp_z_value = _optional_float(dvp_z.get(stamp))
        gcf_z_value = _optional_float(gcf_z.get(stamp))
        sofr_value = _optional_float(sofr.get(stamp))
        effr_value = _optional_float(effr.get(stamp))
        spread_value = _optional_float(spread.get(stamp))
        spread_d5 = _optional_float(spread_d5_series.get(stamp))
        mmf_value, mmf_z_value, mmf_delta = _mmf_asof(mmf, mmf_z_monthly, mmf_d1m, release_date)
        full_pack = evaluate_stfm_full_pack_gate(
            dvp_z=dvp_z_value,
            gcf_z=gcf_z_value,
            sofr_effr_d5_bp=spread_d5,
        )
        sofr_only = evaluate_sofr_only_gate(sofr_effr_d5_bp=spread_d5)
        rows.append(
            StfmDailySnapshot(
                observation_date=observation_date,
                release_date=release_date,
                dvp_volume=dvp_value,
                gcf_volume=gcf_value,
                dvp_z=dvp_z_value,
                gcf_z=gcf_z_value,
                dvp_d5_pct=_optional_float(dvp_d5.get(stamp)),
                dvp_d20_pct=_optional_float(dvp_d20.get(stamp)),
                gcf_d5_pct=_optional_float(gcf_d5.get(stamp)),
                gcf_d20_pct=_optional_float(gcf_d20.get(stamp)),
                mmf_total=mmf_value,
                mmf_z=mmf_z_value,
                mmf_d1m_pct=mmf_delta,
                sofr=sofr_value,
                effr=effr_value,
                sofr_effr_spread_bp=spread_value,
                sofr_effr_d5_bp=spread_d5,
                spy_return_pct=_optional_float(spy_return.get(stamp)) if not spy_return.empty else None,
                spy_realized_vol_20d=_optional_float(spy_vol.get(stamp)) if not spy_vol.empty else None,
                full_pack_gate=full_pack,
                sofr_only_gate=sofr_only,
            )
        )
    coverage = summarize_stfm_coverage(rows, bundle=bundle)
    abort_reasons = stfm_panel_abort_reasons(rows, coverage=coverage, bundle=bundle)
    return StfmPanel(
        recipe=stfm_recipe_manifest(),
        rows=tuple(rows),
        source=bundle.source,
        coverage=coverage,
        abort_reasons=abort_reasons,
    )


def build_hy_keep_panel(bundle: StfmSeriesBundle) -> HyKeepPanel:
    hy = _keep_series(bundle.hy_observations, "hy_oas")
    ig = _keep_series(bundle.hy_observations, "ig_oas")
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
        rows.append(
            HyKeepDailySnapshot(
                as_of=as_of,
                hy_oas=_optional_float(hy_value),
                ig_oas=_optional_float(ig.get(stamp)) if not ig.empty else None,
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


def build_nfci_keep_panel(bundle: StfmSeriesBundle) -> NfciKeepPanel:
    ordered = tuple(
        sorted(bundle.nfci_observations, key=lambda row: (row.release_date, row.observation_week_end))
    )
    nfci_count = len(ordered)
    if not ordered:
        reasons = (
            f"0 KEEP NFCI weekly observations are available; {MIN_NFCI_WEEKS_HARD} are required. "
            "Nested kill-switch vs NFCI cannot be scored.",
        )
        return NfciKeepPanel(
            recipe=nfci_keep_recipe_manifest(),
            rows=(),
            nfci_count=0,
            abort_reasons=reasons,
        )
    values = [row.nfci for row in ordered]
    rows: list[NfciKeepWeeklySnapshot] = []
    rising_streak = 0
    for index, observation in enumerate(ordered):
        d4w = None
        if index >= NFCI_DELTA_WEEKS:
            d4w = observation.nfci - values[index - NFCI_DELTA_WEEKS]
        if d4w is None:
            rising_streak = 0
        elif d4w > 0:
            rising_streak += 1
        else:
            rising_streak = 0
        rows.append(
            NfciKeepWeeklySnapshot(
                observation_week_end=observation.observation_week_end,
                release_date=observation.release_date,
                nfci=observation.nfci,
                nfci_d4w=d4w,
                rising_streak=rising_streak,
                gate=evaluate_nfci_keep_gate(
                    nfci=observation.nfci,
                    nfci_d4w=d4w,
                    rising_streak=rising_streak,
                ),
            )
        )
    abort_reasons = ()
    if nfci_count < MIN_NFCI_WEEKS_HARD:
        abort_reasons = (
            f"{nfci_count} KEEP NFCI weekly observations are available; "
            f"{MIN_NFCI_WEEKS_HARD} are required. Nested kill-switch vs NFCI cannot be scored.",
        )
    return NfciKeepPanel(
        recipe=nfci_keep_recipe_manifest(),
        rows=tuple(rows),
        nfci_count=nfci_count,
        abort_reasons=abort_reasons,
    )


def summarize_stfm_coverage(
    rows: Sequence[StfmDailySnapshot],
    *,
    bundle: StfmSeriesBundle,
) -> dict[str, Any]:
    known = sum(row.full_pack_gate.status in {"full", "throttle"} for row in rows)
    return {
        "row_count": len(rows),
        "source": bundle.source,
        "dvp_count": _numeric_count(bundle.series.get(MNEMONIC_DVP_VOLUME, ())),
        "gcf_count": _numeric_count(bundle.series.get(MNEMONIC_GCF_VOLUME, ())),
        "sofr_count": _numeric_count(bundle.series.get(MNEMONIC_SOFR, ())),
        "effr_count": _numeric_count(bundle.series.get(MNEMONIC_EFFR, ())),
        "mmf_count": _numeric_count(bundle.series.get(MNEMONIC_MMF_TOTAL, ())),
        "null_counts": dict(bundle.null_counts),
        "gate_full_days": sum(row.full_pack_gate.status == "full" for row in rows),
        "gate_throttle_days": sum(row.full_pack_gate.status == "throttle" for row in rows),
        "gate_unknown_days": sum(row.full_pack_gate.status == "unknown" for row in rows),
        "sofr_only_throttle_days": sum(row.sofr_only_gate.status == "throttle" for row in rows),
        "known_gate_share": None if not rows else round(known / len(rows), 6),
        "meets_hard_minimum": min(
            _numeric_count(bundle.series.get(MNEMONIC_DVP_VOLUME, ())),
            _numeric_count(bundle.series.get(MNEMONIC_GCF_VOLUME, ())),
            _numeric_count(bundle.series.get(MNEMONIC_SOFR, ())),
            _numeric_count(bundle.series.get(MNEMONIC_EFFR, ())),
        )
        >= MIN_STFM_SESSIONS_HARD,
        "join_on": "release_date",
        "roro_ingest_v1": RORO_INGEST_V1,
    }


def stfm_panel_abort_reasons(
    rows: Sequence[StfmDailySnapshot],
    *,
    coverage: Mapping[str, Any],
    bundle: StfmSeriesBundle,
) -> tuple[str, ...]:
    reasons: list[str] = []
    daily_count = min(
        int(coverage.get("dvp_count") or 0),
        int(coverage.get("gcf_count") or 0),
        int(coverage.get("sofr_count") or 0),
        int(coverage.get("effr_count") or 0),
    )
    if daily_count < MIN_STFM_SESSIONS_HARD:
        reasons.append(
            f"{daily_count} aligned OFR STFM daily observations are available; "
            f"{MIN_STFM_SESSIONS_HARD} are required. FAIL data-blocked."
        )
    mmf_count = int(coverage.get("mmf_count") or 0)
    if mmf_count < MIN_MMF_MONTHS_HARD:
        reasons.append(
            f"{mmf_count} MMF months are available; {MIN_MMF_MONTHS_HARD} are required. "
            "FAIL data-blocked."
        )
    if not rows:
        reasons.append("The release-dated STFM panel is empty.")
    return tuple(reasons)


def build_stfm_regime_view(panel: StfmPanel) -> StfmRegimeView:
    latest = panel.rows[-1] if panel.rows else None
    warnings = list(panel.abort_reasons)
    if latest is None:
        unknown = evaluate_stfm_full_pack_gate(dvp_z=None, gcf_z=None, sofr_effr_d5_bp=None)
        return StfmRegimeView(
            mode=STFM_MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            recipe_version=STFM_RECIPE_VERSION,
            as_of_date=None,
            snapshot=None,
            gate=unknown.to_dict(),
            sofr_only_gate=evaluate_sofr_only_gate(sofr_effr_d5_bp=None).to_dict(),
            summary="OFR STFM funding-liquidity metrics are unavailable.",
            warnings=warnings,
            updated_at=datetime.now(UTC).isoformat(),
        )
    coverage_score = int(
        round(
            min(
                100.0,
                100.0
                * (
                    (1.0 if latest.dvp_z is not None or latest.gcf_z is not None else 0.0) * 0.4
                    + (1.0 if latest.sofr_effr_d5_bp is not None else 0.0) * 0.4
                    + (1.0 if latest.mmf_total is not None else 0.0) * 0.2
                ),
            )
        )
    )
    gate_status = latest.full_pack_gate.status
    match gate_status:
        case "full":
            summary = (
                "STFM funding-liquidity regime is full-risk-on on the frozen joint "
                "volume-drop + spread-widen flag. This does not change live recommendations."
            )
            status = "constructive"
        case "throttle":
            summary = (
                "STFM funding-liquidity regime throttles long-screen aggressiveness on "
                "the frozen joint volume-drop + spread-widen flag. This does not change "
                "live recommendations."
            )
            status = "cautious"
        case "unknown":
            summary = (
                "STFM funding-liquidity regime cannot be read because volume z-scores or "
                "the SOFR-EFFR change is missing."
            )
            status = "unavailable"
        case _ as unreachable:
            assert_never(unreachable)
    evidence = [
        f"Observation date: {latest.observation_date.isoformat()}.",
        f"Release date used for joins: {latest.release_date.isoformat()}.",
        f"DVP z-score: {_fmt(latest.dvp_z)}.",
        f"GCF z-score: {_fmt(latest.gcf_z)}.",
        f"SOFR-EFFR 5-session Δ: {_fmt(latest.sofr_effr_d5_bp, suffix=' bp')}.",
        f"MMF 1-month Δ: {_fmt(latest.mmf_d1m_pct, suffix='%')}.",
        f"Frozen full-pack gate is {gate_status_label(gate_status)}.",
        f"SOFR-only control is {gate_status_label(latest.sofr_only_gate.status)}.",
    ]
    return StfmRegimeView(
        mode=STFM_MODE,
        status=status,
        applied_impact=0,
        coverage_score=coverage_score,
        recipe_version=STFM_RECIPE_VERSION,
        as_of_date=latest.release_date.isoformat(),
        snapshot=latest.to_dict(),
        gate=latest.full_pack_gate.to_dict(),
        sofr_only_gate=latest.sofr_only_gate.to_dict(),
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings + list(latest.full_pack_gate.reasons))),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _ofr_series(points: Sequence[OfrPoint]) -> pd.Series:
    values = {
        pd.Timestamp(row.release_date): row.value
        for row in points
        if row.value is not None
    }
    if not values:
        return pd.Series(dtype=float)
    series = pd.Series(values, dtype=float).sort_index()
    series.index = pd.to_datetime(series.index).tz_localize(None)
    return series[~series.index.duplicated(keep="last")]


def _observation_by_release(bundle: StfmSeriesBundle) -> dict[date, date]:
    mapping: dict[date, date] = {}
    for mnemonic in (*DAILY_VOLUME_MNEMONICS, *DAILY_RATE_MNEMONICS):
        for row in bundle.series.get(mnemonic, ()):
            mapping[row.release_date] = row.observation_date
    return mapping


def _keep_series(observations: Sequence[HyKeepObservation], field_name: str) -> pd.Series:
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


def _union_index(series_list: Sequence[pd.Series]) -> pd.DatetimeIndex:
    frames = [series for series in series_list if not series.empty]
    if not frames:
        return pd.DatetimeIndex([])
    index = frames[0].index
    for series in frames[1:]:
        index = index.union(series.index)
    return pd.DatetimeIndex(sorted(index))


def _causal_zscore(series: pd.Series, *, window: int, min_obs: int) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    zscores: dict[pd.Timestamp, float] = {}
    ordered = series.sort_index()
    for stamp, value in ordered.items():
        prior = ordered.loc[ordered.index < stamp].iloc[-window:]
        if int(prior.count()) < min_obs:
            continue
        mean = float(prior.mean())
        std = float(prior.std(ddof=0))
        if std <= 0:
            continue
        zscores[pd.Timestamp(stamp)] = (float(value) - mean) / std
    if not zscores:
        return pd.Series(dtype=float)
    result = pd.Series(zscores, dtype=float).sort_index()
    result.index = pd.to_datetime(result.index).tz_localize(None)
    return result


def _percent_change(series: pd.Series, periods: int) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    prior = series.shift(periods)
    changed = (series / prior - 1.0) * 100.0
    return changed.replace([pd.NA], None)


def _change(series: pd.Series, periods: int) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    return series.diff(periods)


def _spread_bp(sofr: pd.Series, effr: pd.Series) -> pd.Series:
    if sofr.empty or effr.empty:
        return pd.Series(dtype=float)
    aligned = pd.concat({"sofr": sofr, "effr": effr}, axis=1).dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    return (aligned["sofr"] - aligned["effr"]) * 100.0


def _mmf_asof(
    mmf: pd.Series,
    mmf_z: pd.Series,
    mmf_d1m: pd.Series,
    as_of: date,
) -> tuple[float | None, float | None, float | None]:
    if mmf.empty:
        return None, None, None
    eligible = mmf.loc[mmf.index.date <= as_of]
    if eligible.empty:
        return None, None, None
    stamp = eligible.index[-1]
    return (
        _optional_float(mmf.get(stamp)),
        _optional_float(mmf_z.get(stamp)),
        _optional_float(mmf_d1m.get(stamp)),
    )


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


def _numeric_count(rows: Sequence[OfrPoint]) -> int:
    return sum(row.value is not None for row in rows)


def _empty_stfm_coverage(bundle: StfmSeriesBundle) -> dict[str, Any]:
    return {
        "row_count": 0,
        "source": bundle.source,
        "dvp_count": _numeric_count(bundle.series.get(MNEMONIC_DVP_VOLUME, ())),
        "gcf_count": _numeric_count(bundle.series.get(MNEMONIC_GCF_VOLUME, ())),
        "sofr_count": _numeric_count(bundle.series.get(MNEMONIC_SOFR, ())),
        "effr_count": _numeric_count(bundle.series.get(MNEMONIC_EFFR, ())),
        "mmf_count": _numeric_count(bundle.series.get(MNEMONIC_MMF_TOTAL, ())),
        "null_counts": dict(bundle.null_counts),
        "gate_full_days": 0,
        "gate_throttle_days": 0,
        "gate_unknown_days": 0,
        "sofr_only_throttle_days": 0,
        "known_gate_share": None,
        "meets_hard_minimum": False,
        "join_on": "release_date",
        "roro_ingest_v1": RORO_INGEST_V1,
    }


__all__ = [
    "GateStatus",
    "HyKeepDailySnapshot",
    "HyKeepGateDecision",
    "HyKeepPanel",
    "NfciKeepGateDecision",
    "NfciKeepPanel",
    "NfciKeepWeeklySnapshot",
    "StfmDailySnapshot",
    "StfmGateDecision",
    "StfmPanel",
    "StfmRegimeView",
    "build_hy_keep_panel",
    "build_nfci_keep_panel",
    "build_stfm_panel",
    "build_stfm_regime_view",
    "evaluate_hy_keep_gate",
    "evaluate_nfci_keep_gate",
    "evaluate_sofr_only_gate",
    "evaluate_stfm_full_pack_gate",
    "gate_status_label",
    "stfm_panel_abort_reasons",
    "summarize_stfm_coverage",
]
