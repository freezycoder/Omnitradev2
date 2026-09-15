from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal, Mapping, Sequence
from typing import assert_never

import pandas as pd

from config.credit_regime import (
    CREDIT_MODE,
    CREDIT_RECIPE_VERSION,
    ICE_REDISTRIBUTION_NOTICE,
    LEAD_LAG_OFFSETS,
    MIN_SERIES_SESSIONS_HARD,
    MIN_SERIES_SESSIONS_RECOMMENDED,
    PERCENTILE_MIN_OBSERVATIONS,
    PERCENTILE_THROTTLE,
    PERCENTILE_WINDOW_SESSIONS,
    SPY_VOL_WINDOW_SESSIONS,
    THROTTLE_WEIGHT,
    VELOCITY_WIDENING_BP,
    VELOCITY_WINDOW_SESSIONS,
    WEEKLY_WINDOW_SESSIONS,
    credit_recipe_manifest,
)
from providers.macro.credit_oas_client import CreditSeriesBundle, CreditSeriesObservation


GateStatus = Literal["full", "throttle", "unknown"]


@dataclass(frozen=True)
class CreditGateDecision:
    status: GateStatus
    hy_oas: float | None
    hy_oas_d20_bp: float | None
    hy_oas_percentile_252: float | None
    percentile_observations: int
    throttle_weight: float | None
    reasons: tuple[str, ...]
    recipe_version: str = CREDIT_RECIPE_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class CreditDailySnapshot:
    as_of: date
    hy_oas: float | None
    ig_oas: float | None
    hy_ig_gap: float | None
    hy_oas_d20_bp: float | None
    hy_oas_d5_bp: float | None
    hy_oas_percentile_252: float | None
    percentile_observations: int
    spy_return_pct: float | None
    spy_realized_vol_20d: float | None
    gate: CreditGateDecision

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of"] = self.as_of.isoformat()
        payload["gate"] = self.gate.to_dict()
        return payload


@dataclass(frozen=True)
class CreditRegimeView:
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
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CreditPanel:
    recipe: dict[str, Any]
    rows: tuple[CreditDailySnapshot, ...]
    source: str
    hy_count: int
    ig_count: int
    history_sessions: int
    coverage: dict[str, Any]
    abort_reasons: tuple[str, ...]
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe": self.recipe,
            "row_count": len(self.rows),
            "source": self.source,
            "hy_count": self.hy_count,
            "ig_count": self.ig_count,
            "history_sessions": self.history_sessions,
            "coverage": self.coverage,
            "abort_reasons": list(self.abort_reasons),
            "ice_redistribution_notice": self.ice_redistribution_notice,
            "latest": self.rows[-1].to_dict() if self.rows else None,
        }

    def snapshot_on(self, as_of: date) -> CreditDailySnapshot | None:
        for row in reversed(self.rows):
            if row.as_of == as_of:
                return row
        return None

    def gate_status_on(self, as_of: date) -> GateStatus:
        snapshot = self.snapshot_on(as_of)
        if snapshot is None:
            return "unknown"
        return snapshot.gate.status


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


def evaluate_gate(
    *,
    hy_oas: float | None,
    hy_oas_d20_bp: float | None,
    hy_oas_percentile_252: float | None,
    percentile_observations: int,
) -> CreditGateDecision:
    reasons: list[str] = []
    if hy_oas is None or hy_oas_d20_bp is None:
        reasons.append("HY OAS level or 20-session change is missing.")
        return CreditGateDecision(
            status="unknown",
            hy_oas=hy_oas,
            hy_oas_d20_bp=hy_oas_d20_bp,
            hy_oas_percentile_252=hy_oas_percentile_252,
            percentile_observations=percentile_observations,
            throttle_weight=None,
            reasons=tuple(reasons),
        )

    velocity_hit = hy_oas_d20_bp > VELOCITY_WIDENING_BP
    percentile_ready = (
        percentile_observations >= PERCENTILE_MIN_OBSERVATIONS and hy_oas_percentile_252 is not None
    )
    percentile_hit = percentile_ready and hy_oas_percentile_252 >= PERCENTILE_THROTTLE
    if velocity_hit:
        reasons.append(
            f"20-session HY OAS change is {hy_oas_d20_bp:.1f} bp, above the frozen "
            f"{VELOCITY_WIDENING_BP:.0f} bp widening threshold."
        )
    if percentile_hit:
        reasons.append(
            f"Causal trailing-{PERCENTILE_WINDOW_SESSIONS} HY OAS percentile is "
            f"{hy_oas_percentile_252:.1f}, at or above {PERCENTILE_THROTTLE:.0f}."
        )
    if velocity_hit or percentile_hit:
        status: GateStatus = "throttle"
        weight: float | None = THROTTLE_WEIGHT
        reasons.append(
            f"Long-screen aggressiveness is throttled to {THROTTLE_WEIGHT:.0%} weight. "
            "This does not change live recommendations."
        )
    else:
        status = "full"
        weight = 1.0
        reasons.append(
            f"20-session HY OAS change is {hy_oas_d20_bp:.1f} bp and the causal "
            f"trailing percentile is "
            f"{'n/a' if hy_oas_percentile_252 is None else f'{hy_oas_percentile_252:.1f}'}; "
            "the frozen throttle is not engaged."
        )
    return CreditGateDecision(
        status=status,
        hy_oas=hy_oas,
        hy_oas_d20_bp=hy_oas_d20_bp,
        hy_oas_percentile_252=hy_oas_percentile_252,
        percentile_observations=percentile_observations,
        throttle_weight=weight,
        reasons=tuple(reasons),
    )


def build_credit_panel(
    bundle: CreditSeriesBundle,
    *,
    spy_history: pd.DataFrame | None = None,
) -> CreditPanel:
    hy = _series_from_observations(bundle.observations, "hy_oas")
    ig = _series_from_observations(bundle.observations, "ig_oas")
    spy_close = _close_series(spy_history)
    spy_return = spy_close.pct_change() * 100.0 if not spy_close.empty else pd.Series(dtype=float)
    spy_vol = (
        spy_close.pct_change().rolling(SPY_VOL_WINDOW_SESSIONS).std() * (252.0 ** 0.5)
        if not spy_close.empty
        else pd.Series(dtype=float)
    )
    if hy.empty:
        coverage = _empty_coverage(bundle)
        return CreditPanel(
            recipe=credit_recipe_manifest(),
            rows=(),
            source=bundle.source,
            hy_count=bundle.hy_count,
            ig_count=bundle.ig_count,
            history_sessions=0,
            coverage=coverage,
            abort_reasons=panel_abort_reasons((), coverage=coverage, hy_count=bundle.hy_count),
        )

    d20 = hy.diff(VELOCITY_WINDOW_SESSIONS) * 100.0
    d5 = hy.diff(WEEKLY_WINDOW_SESSIONS) * 100.0
    gap = hy.subtract(ig) if not ig.empty else pd.Series(dtype=float)
    rows: list[CreditDailySnapshot] = []
    for stamp, hy_value in hy.items():
        as_of = pd.Timestamp(stamp).date()
        prior = hy.loc[hy.index < stamp].iloc[-PERCENTILE_WINDOW_SESSIONS:]
        percentile_obs = int(prior.count())
        percentile = _percentile_of(float(hy_value), prior) if percentile_obs else None
        d20_bp = _optional_float(d20.get(stamp))
        gate = evaluate_gate(
            hy_oas=_optional_float(hy_value),
            hy_oas_d20_bp=d20_bp,
            hy_oas_percentile_252=percentile,
            percentile_observations=percentile_obs,
        )
        ig_value = _optional_float(ig.get(stamp)) if not ig.empty else None
        rows.append(
            CreditDailySnapshot(
                as_of=as_of,
                hy_oas=_optional_float(hy_value),
                ig_oas=ig_value,
                hy_ig_gap=_optional_float(gap.get(stamp)) if not gap.empty else None,
                hy_oas_d20_bp=d20_bp,
                hy_oas_d5_bp=_optional_float(d5.get(stamp)),
                hy_oas_percentile_252=percentile,
                percentile_observations=percentile_obs,
                spy_return_pct=_optional_float(spy_return.get(stamp)) if not spy_return.empty else None,
                spy_realized_vol_20d=_optional_float(spy_vol.get(stamp)) if not spy_vol.empty else None,
                gate=gate,
            )
        )
    coverage = summarize_panel_coverage(rows, bundle=bundle)
    abort_reasons = panel_abort_reasons(rows, coverage=coverage, hy_count=bundle.hy_count)
    return CreditPanel(
        recipe=credit_recipe_manifest(),
        rows=tuple(rows),
        source=bundle.source,
        hy_count=bundle.hy_count,
        ig_count=bundle.ig_count,
        history_sessions=len(rows),
        coverage=coverage,
        abort_reasons=abort_reasons,
    )


def summarize_panel_coverage(
    rows: Sequence[CreditDailySnapshot],
    *,
    bundle: CreditSeriesBundle,
) -> dict[str, Any]:
    known = [row for row in rows if row.gate.status != "unknown"]
    throttle_days = sum(row.gate.status == "throttle" for row in rows)
    full_days = sum(row.gate.status == "full" for row in rows)
    unknown_days = sum(row.gate.status == "unknown" for row in rows)
    d20_ready = sum(row.hy_oas_d20_bp is not None for row in rows)
    gap_ready = sum(row.hy_ig_gap is not None for row in rows)
    percentile_ready = sum(
        row.percentile_observations >= PERCENTILE_MIN_OBSERVATIONS for row in rows
    )
    return {
        "hy_count": bundle.hy_count,
        "ig_count": bundle.ig_count,
        "session_count": len(rows),
        "source": bundle.source,
        "first_date": bundle.first_date.isoformat() if bundle.first_date else None,
        "last_date": bundle.last_date.isoformat() if bundle.last_date else None,
        "gate_full_days": full_days,
        "gate_throttle_days": throttle_days,
        "gate_unknown_days": unknown_days,
        "velocity_ready_days": d20_ready,
        "gap_ready_days": gap_ready,
        "percentile_ready_days": percentile_ready,
        "known_gate_share": (len(known) / len(rows)) if rows else None,
        "meets_hard_minimum": bundle.hy_count >= MIN_SERIES_SESSIONS_HARD,
        "meets_recommended_minimum": bundle.hy_count >= MIN_SERIES_SESSIONS_RECOMMENDED,
        "history_sessions_recommended": MIN_SERIES_SESSIONS_RECOMMENDED,
        "data_blocked": bundle.hy_count < MIN_SERIES_SESSIONS_HARD,
        "march_2020_in_window": bool(bundle.history_plan.get("march_2020_in_window")),
    }


def panel_abort_reasons(
    rows: Sequence[CreditDailySnapshot],
    *,
    coverage: Mapping[str, Any],
    hy_count: int,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if hy_count < MIN_SERIES_SESSIONS_HARD:
        reasons.append(
            f"{hy_count} HY OAS observations are available; "
            f"{MIN_SERIES_SESSIONS_HARD} are required. FAIL data-blocked."
        )
    if not rows:
        reasons.append("The daily credit panel is empty.")
    velocity_ready = int(coverage.get("velocity_ready_days") or 0)
    if rows and velocity_ready < VELOCITY_WINDOW_SESSIONS:
        reasons.append(
            f"Only {velocity_ready} sessions have a 20-session HY OAS change; "
            f"{VELOCITY_WINDOW_SESSIONS} are required."
        )
    return tuple(reasons)


def build_credit_regime_view(panel: CreditPanel) -> CreditRegimeView:
    latest = panel.rows[-1] if panel.rows else None
    warnings = list(panel.abort_reasons)
    warnings.append(ICE_REDISTRIBUTION_NOTICE)
    if latest is None:
        return CreditRegimeView(
            mode=CREDIT_MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            recipe_version=CREDIT_RECIPE_VERSION,
            as_of_date=None,
            snapshot=None,
            gate=evaluate_gate(
                hy_oas=None,
                hy_oas_d20_bp=None,
                hy_oas_percentile_252=None,
                percentile_observations=0,
            ).to_dict(),
            summary="Credit OAS regime metrics are unavailable.",
            warnings=list(dict.fromkeys(warnings)),
            updated_at=datetime.now(UTC).isoformat(),
        )

    coverage_score = int(
        round(
            min(
                100.0,
                100.0
                * (
                    (1.0 if latest.hy_oas is not None else 0.0) * 0.5
                    + (1.0 if latest.hy_oas_d20_bp is not None else 0.0) * 0.3
                    + (1.0 if latest.hy_ig_gap is not None else 0.0) * 0.2
                ),
            )
        )
    )
    gate_status = latest.gate.status
    match gate_status:
        case "full":
            summary = (
                "Credit regime is full-risk-on on the frozen HY OAS throttle. "
                "This does not change live recommendations."
            )
            status = "constructive"
        case "throttle":
            summary = (
                "Credit regime throttles long-screen aggressiveness on the frozen "
                "HY OAS rule. This does not change live recommendations."
            )
            status = "cautious"
        case "unknown":
            summary = (
                "Credit regime cannot be read because HY OAS level or 20-session "
                "widening is missing."
            )
            status = "unavailable"
        case _ as unreachable:
            assert_never(unreachable)

    evidence = [
        f"HY OAS level: {_fmt(latest.hy_oas)}.",
        f"20-session Δ: {_fmt(latest.hy_oas_d20_bp, suffix=' bp')}.",
        f"Weekly Δ: {_fmt(latest.hy_oas_d5_bp, suffix=' bp')}.",
        f"HY−IG gap: {_fmt(latest.hy_ig_gap)}.",
        f"Causal trailing-{PERCENTILE_WINDOW_SESSIONS} percentile: {_fmt(latest.hy_oas_percentile_252)}.",
        f"Frozen gate is {gate_status_label(gate_status)}.",
    ]
    return CreditRegimeView(
        mode=CREDIT_MODE,
        status=status,
        applied_impact=0,
        coverage_score=coverage_score,
        recipe_version=CREDIT_RECIPE_VERSION,
        as_of_date=latest.as_of.isoformat(),
        snapshot=latest.to_dict(),
        gate=latest.gate.to_dict(),
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings + list(latest.gate.reasons))),
        updated_at=datetime.now(UTC).isoformat(),
    )


def lead_lag_diagnostics(panel: CreditPanel) -> dict[str, Any]:
    pairs = [
        (row.hy_oas_d20_bp, row.spy_return_pct, row.as_of)
        for row in panel.rows
        if row.hy_oas_d20_bp is not None and row.spy_return_pct is not None
    ]
    if len(pairs) < VELOCITY_WINDOW_SESSIONS:
        return {
            "status": "unavailable",
            "message": "Not enough overlapping HY OAS 20-session changes and SPY returns.",
            "offsets": list(LEAD_LAG_OFFSETS),
            "correlations": [],
            "interpretation": (
                "Lead/lag is descriptive only and is not an input to the frozen gate."
            ),
        }
    velocity = pd.Series({as_of: d20 for d20, _spy, as_of in pairs}, dtype=float).sort_index()
    spy = pd.Series({as_of: spy_ret for _d20, spy_ret, as_of in pairs}, dtype=float).sort_index()
    aligned_v, aligned_s = velocity.align(spy, join="inner")
    correlations: list[dict[str, Any]] = []
    for offset in LEAD_LAG_OFFSETS:
        shifted = aligned_s.shift(-offset)
        joined = pd.concat([aligned_v, shifted], axis=1).dropna()
        if len(joined) < VELOCITY_WINDOW_SESSIONS:
            corr = None
        else:
            corr = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
            if corr != corr:
                corr = None
        correlations.append(
            {
                "oas_lead_sessions": offset,
                "n": int(len(joined)),
                "pearson": None if corr is None else round(corr, 6),
            }
        )
    coincident = next((row["pearson"] for row in correlations if row["oas_lead_sessions"] == 0), None)
    leading = [row for row in correlations if row["oas_lead_sessions"] > 0 and row["pearson"] is not None]
    best_lead = max(leading, key=lambda row: abs(row["pearson"])) if leading else None
    return {
        "status": "available",
        "offsets": list(LEAD_LAG_OFFSETS),
        "correlations": correlations,
        "coincident_pearson": coincident,
        "strongest_positive_lead": best_lead,
        "interpretation": (
            "Positive oas_lead_sessions means 20-session HY OAS widening is aligned "
            "with later SPY returns. This diagnostic is not used to retune the gate."
        ),
    }


def crisis_descriptive_overlay(panel: CreditPanel) -> dict[str, Any]:
    window = [
        row
        for row in panel.rows
        if date(2020, 2, 1) <= row.as_of <= date(2020, 4, 30) and row.hy_oas is not None
    ]
    if not window:
        return {
            "status": "not_in_window",
            "message": (
                "March 2020 is outside the current FRED public window. The episode is "
                "descriptive only and is not a tune target for credit-gate-v1."
            ),
        }
    peak = max(window, key=lambda row: row.hy_oas or 0.0)
    spy_window = [row for row in window if row.spy_return_pct is not None]
    return {
        "status": "descriptive_only",
        "tune_target": False,
        "peak_hy_oas": peak.hy_oas,
        "peak_hy_oas_date": peak.as_of.isoformat(),
        "spy_sessions_in_window": len(spy_window),
        "message": (
            "March 2020 HY OAS spike is reported as a coincident stress anecdote only. "
            "It is not used to choose the frozen 30 bp / 80th-percentile rule."
        ),
    }


def _series_from_observations(
    observations: Sequence[CreditSeriesObservation],
    field_name: str,
) -> pd.Series:
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
    if len(values) < PERCENTILE_MIN_OBSERVATIONS:
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
    return f"{value:.2f}{suffix}"


def _empty_coverage(bundle: CreditSeriesBundle) -> dict[str, Any]:
    return {
        "hy_count": bundle.hy_count,
        "ig_count": bundle.ig_count,
        "session_count": 0,
        "source": bundle.source,
        "first_date": bundle.first_date.isoformat() if bundle.first_date else None,
        "last_date": bundle.last_date.isoformat() if bundle.last_date else None,
        "gate_full_days": 0,
        "gate_throttle_days": 0,
        "gate_unknown_days": 0,
        "velocity_ready_days": 0,
        "gap_ready_days": 0,
        "percentile_ready_days": 0,
        "known_gate_share": None,
        "meets_hard_minimum": False,
        "meets_recommended_minimum": False,
        "history_sessions_recommended": MIN_SERIES_SESSIONS_RECOMMENDED,
        "data_blocked": True,
        "march_2020_in_window": False,
    }


__all__ = [
    "CreditDailySnapshot",
    "CreditGateDecision",
    "CreditPanel",
    "CreditRegimeView",
    "GateStatus",
    "build_credit_panel",
    "build_credit_regime_view",
    "crisis_descriptive_overlay",
    "evaluate_gate",
    "gate_status_label",
    "lead_lag_diagnostics",
    "panel_abort_reasons",
    "summarize_panel_coverage",
]
