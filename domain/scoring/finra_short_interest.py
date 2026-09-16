from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.finra_short_interest import (
    DAYS_TO_COVER_ELEVATED,
    DAYS_TO_COVER_HIGH,
    FEATURE_FAMILY,
    FEATURE_FAMILY_LABEL,
    LEGAL_GATE,
    MODE,
    NO_SQUEEZE_POLICY,
    PCT_CHANGE_HIGH,
    PCT_CHANGE_LOW,
    PCT_FLOAT_COVERAGE_FLOOR,
    PCT_FLOAT_REASON,
    PCT_FLOAT_STATUS,
    PROVENANCE,
)
from domain.research.lifecycle import (
    EXPERIMENT_FINRA_SHORT_INTEREST,
    LifecycleLabel,
    LifecycleStage,
)
from domain.research.promotion import instantiate_sealed_shadow_view, seal_shadow_live_fields
from providers.market.finra_short_interest_client import FinraShortInterestRow


NOT_SHORT_VOLUME_LABEL = "Not daily FINRA short-sale volume"
LAG_POLICY = (
    "Event date is the Rule 4560 publication date (7th weekday after settlement), "
    "never the settlement date."
)


@dataclass(frozen=True)
class FinraShortInterestView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    feature_family: str
    feature_label: str
    provenance: str
    symbol: str | None
    settlement_date: str | None
    publication_date: str | None
    event_date: str | None
    lag_calendar_days: int | None
    short_shares: float | None
    previous_short_shares: float | None
    pct_change_prior: float | None
    days_to_cover: float | None
    log_short_shares: float | None
    average_daily_volume: float | None
    pct_float: float | None
    pct_float_status: str
    pct_float_coverage_floor: float
    delta_high: bool
    delta_low: bool
    dtc_elevated: bool
    dtc_high: bool
    not_short_volume: bool
    squeeze_narrative: bool
    legal_gate: dict[str, Any]
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None
    lifecycle_label: str = LifecycleLabel.UNVERIFIED.value
    lifecycle_stage: str = LifecycleStage.CANDIDATE.value
    experiment_ids: tuple[str, ...] = (EXPERIMENT_FINRA_SHORT_INTEREST,)
    promotion_receipts: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def frozen_delta_high(pct_change_prior: float | None) -> bool:
    return pct_change_prior is not None and pct_change_prior >= PCT_CHANGE_HIGH


def frozen_delta_low(pct_change_prior: float | None) -> bool:
    return pct_change_prior is not None and pct_change_prior <= PCT_CHANGE_LOW


def frozen_dtc_elevated(days_to_cover: float | None) -> bool:
    return days_to_cover is not None and days_to_cover >= DAYS_TO_COVER_ELEVATED


def frozen_dtc_high(days_to_cover: float | None) -> bool:
    return days_to_cover is not None and days_to_cover >= DAYS_TO_COVER_HIGH


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def build_finra_short_interest_view(
    row: FinraShortInterestRow | None,
    *,
    warning: str | None = None,
) -> FinraShortInterestView:
    warnings = [LAG_POLICY, PCT_FLOAT_REASON, NO_SQUEEZE_POLICY]
    if warning:
        warnings.append(warning)
    if row is None:
        return build_unavailable_finra_short_interest_view(
            warning or "FINRA biweekly short interest is unavailable for this ticker."
        )

    delta_high = frozen_delta_high(row.pct_change_prior)
    delta_low = frozen_delta_low(row.pct_change_prior)
    dtc_elevated = frozen_dtc_elevated(row.days_to_cover)
    dtc_high = frozen_dtc_high(row.days_to_cover)
    pct_change = _round(row.pct_change_prior, 2)
    dtc = _round(row.days_to_cover, 2)
    evidence = [
        (
            f"{row.symbol} shortShares={row.short_shares:.0f} published "
            f"{row.publication_date.isoformat()} (settlement {row.settlement_date.isoformat()}, "
            f"lag {row.lag_calendar_days}d)."
        ),
        (
            f"pctChangePrior={pct_change if pct_change is not None else 'n/a'}; "
            f"daysToCover={dtc if dtc is not None else 'n/a'}."
        ),
        (
            "Frozen gates: "
            f"delta_high(>={PCT_CHANGE_HIGH:g}%)={str(delta_high).lower()}, "
            f"delta_low(<={PCT_CHANGE_LOW:g}%)={str(delta_low).lower()}, "
            f"dtc_elevated(>={DAYS_TO_COVER_ELEVATED:g})={str(dtc_elevated).lower()}, "
            f"dtc_high(>={DAYS_TO_COVER_HIGH:g})={str(dtc_high).lower()}."
        ),
        LAG_POLICY,
        "This is biweekly FINRA short interest, not daily CNMS short-sale volume.",
        "pctFloat is deferred; no frozen public-float series is attached.",
    ]
    change_text = (
        f"{pct_change:+.2f}% vs the prior settlement"
        if pct_change is not None
        else "an unreported prior-cycle change"
    )
    dtc_text = f"{dtc:.2f} days-to-cover" if dtc is not None else "unreported days-to-cover"
    summary = (
        f"Published short interest on {row.publication_date.isoformat()} was "
        f"{row.short_shares:,.0f} shares ({change_text}; {dtc_text}). "
        "This shadow positioning factor does not change the live recommendation."
    )
    return seal_shadow_live_fields(
        FinraShortInterestView(
            mode=MODE,
            status="available",
            applied_impact=0,
            coverage_score=100,
            feature_family=FEATURE_FAMILY,
            feature_label=FEATURE_FAMILY_LABEL,
            provenance=row.provenance,
            symbol=row.symbol,
            settlement_date=row.settlement_date.isoformat(),
            publication_date=row.publication_date.isoformat(),
            event_date=row.event_date.isoformat(),
            lag_calendar_days=row.lag_calendar_days,
            short_shares=_round(row.short_shares, 4),
            previous_short_shares=_round(row.previous_short_shares, 4),
            pct_change_prior=pct_change,
            days_to_cover=dtc,
            log_short_shares=_round(row.log_short_shares, 6),
            average_daily_volume=_round(row.average_daily_volume, 4),
            pct_float=None,
            pct_float_status=PCT_FLOAT_STATUS,
            pct_float_coverage_floor=PCT_FLOAT_COVERAGE_FLOOR,
            delta_high=delta_high,
            delta_low=delta_low,
            dtc_elevated=dtc_elevated,
            dtc_high=dtc_high,
            not_short_volume=True,
            squeeze_narrative=False,
            legal_gate=dict(LEGAL_GATE),
            summary=summary,
            evidence=evidence,
            warnings=list(dict.fromkeys(warnings)),
            updated_at=datetime.now(UTC).isoformat(),
            lifecycle_label=LifecycleLabel.UNVERIFIED.value,
            lifecycle_stage=LifecycleStage.CANDIDATE.value,
            experiment_ids=(EXPERIMENT_FINRA_SHORT_INTEREST,),
        )
    )


def build_unavailable_finra_short_interest_view(message: str) -> FinraShortInterestView:
    return seal_shadow_live_fields(
        FinraShortInterestView(
            mode=MODE,
            status="unavailable",
            applied_impact=0,
            coverage_score=0,
            feature_family=FEATURE_FAMILY,
            feature_label=FEATURE_FAMILY_LABEL,
            provenance=PROVENANCE,
            symbol=None,
            settlement_date=None,
            publication_date=None,
            event_date=None,
            lag_calendar_days=None,
            short_shares=None,
            previous_short_shares=None,
            pct_change_prior=None,
            days_to_cover=None,
            log_short_shares=None,
            average_daily_volume=None,
            pct_float=None,
            pct_float_status=PCT_FLOAT_STATUS,
            pct_float_coverage_floor=PCT_FLOAT_COVERAGE_FLOOR,
            delta_high=False,
            delta_low=False,
            dtc_elevated=False,
            dtc_high=False,
            not_short_volume=True,
            squeeze_narrative=False,
            legal_gate=dict(LEGAL_GATE),
            summary=message,
            warnings=[message, LAG_POLICY, PCT_FLOAT_REASON, NO_SQUEEZE_POLICY],
            updated_at=datetime.now(UTC).isoformat(),
            lifecycle_label=LifecycleLabel.UNVERIFIED.value,
            lifecycle_stage=LifecycleStage.CANDIDATE.value,
            experiment_ids=(EXPERIMENT_FINRA_SHORT_INTEREST,),
        )
    )


def finra_short_interest_view_from_dict(payload: dict[str, Any] | None) -> FinraShortInterestView:
    if not isinstance(payload, dict):
        return build_unavailable_finra_short_interest_view(
            "The cached snapshot predates FINRA short-interest analysis."
        )
    values = dict(payload)
    values.setdefault("mode", MODE)
    values.setdefault("applied_impact", 0)
    values.setdefault("feature_family", FEATURE_FAMILY)
    values.setdefault("feature_label", FEATURE_FAMILY_LABEL)
    values.setdefault("provenance", PROVENANCE)
    values.setdefault("not_short_volume", True)
    values.setdefault("squeeze_narrative", False)
    values.setdefault("pct_float", None)
    values.setdefault("pct_float_status", PCT_FLOAT_STATUS)
    values.setdefault("pct_float_coverage_floor", PCT_FLOAT_COVERAGE_FLOOR)
    values.setdefault("legal_gate", dict(LEGAL_GATE))
    values["applied_impact"] = 0
    values["squeeze_narrative"] = False
    values["pct_float"] = None
    values["pct_float_status"] = PCT_FLOAT_STATUS
    return instantiate_sealed_shadow_view(
        FinraShortInterestView,
        values,
        experiment_ids=(EXPERIMENT_FINRA_SHORT_INTEREST,),
    )


__all__ = [
    "FEATURE_FAMILY",
    "FEATURE_FAMILY_LABEL",
    "LAG_POLICY",
    "NOT_SHORT_VOLUME_LABEL",
    "FinraShortInterestView",
    "build_finra_short_interest_view",
    "build_unavailable_finra_short_interest_view",
    "finra_short_interest_view_from_dict",
    "frozen_delta_high",
    "frozen_delta_low",
    "frozen_dtc_elevated",
    "frozen_dtc_high",
]
