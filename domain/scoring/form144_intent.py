from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from config.form144 import (
    CLUSTER_MIN_AFFILIATES,
    CLUSTER_WINDOW_DAYS,
    FORM144_APPLIED_IMPACT,
    FORM144_MODE,
    FORM144_MODELED_IMPACT,
    PRIMARY_SOURCE,
)
from domain.research.form144_features import detect_clusters, eligible_notices, ticker_day_intensity
from domain.research.lifecycle import EXPERIMENT_FORM144, LifecycleLabel, LifecycleStage
from domain.research.promotion import instantiate_sealed_shadow_view
from providers.events.form144_models import Form4Sale, ProposedSaleNotice, parse_iso_date


@dataclass(frozen=True)
class Form144IntentView:
    mode: str
    status: str
    score: int | None
    modeled_impact: int
    applied_impact: int
    coverage_score: int
    primary_source: str
    cluster: bool
    unmatched_intent: bool
    conflict: bool
    affiliate_count: int
    proposed_units: float
    event_date: str | None
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    activation_gate: dict[str, Any] = field(default_factory=dict)
    as_of_date: str | None = None
    updated_at: str | None = None
    lifecycle_label: str = LifecycleLabel.UNVERIFIED.value
    lifecycle_stage: str = LifecycleStage.CANDIDATE.value
    experiment_ids: tuple[str, ...] = (EXPERIMENT_FORM144,)
    promotion_receipts: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _activation_gate() -> dict[str, Any]:
    return {
        "status": "collecting_evidence",
        "automatic_activation": False,
        "live_recommendation_changes": False,
        "alpha_claim": False,
        "jof_car_claim": False,
        "lifecycle_label": LifecycleLabel.UNVERIFIED.value,
        "cluster_n": CLUSTER_MIN_AFFILIATES,
        "cluster_w_days": CLUSTER_WINDOW_DAYS,
    }


def build_form144_intent_view(
    *,
    ticker: str,
    notices: Sequence[ProposedSaleNotice],
    sales: Sequence[Form4Sale] | None = None,
    as_of: str | None = None,
) -> Form144IntentView:
    as_of_date = parse_iso_date(as_of) or datetime.now(UTC).date()
    scoped_notices = [
        row
        for row in eligible_notices(notices)
        if (row.ticker or "").upper() == ticker.upper().strip()
        and (parsed := parse_iso_date(row.intent_date)) is not None
        and parsed <= as_of_date
    ]
    intensities = [
        row
        for row in ticker_day_intensity(scoped_notices)
        if row.ticker == ticker.upper().strip()
    ]
    clusters = [
        event
        for event in detect_clusters(scoped_notices)
        if event.ticker == ticker.upper().strip()
        and (parsed := parse_iso_date(event.as_of)) is not None
        and parsed <= as_of_date
    ]
    latest = intensities[-1] if intensities else None
    cluster = bool(clusters)
    unmatched_intent = bool(latest and latest.notice_count > 0)
    conflict = False
    if latest is not None and sales:
        as_of_sales = [
            sale
            for sale in sales
            if (sale.ticker or "").upper() == ticker.upper().strip()
            and parse_iso_date(sale.event_date) == parse_iso_date(latest.as_of)
        ]
        conflict = latest.cluster and not as_of_sales
        unmatched_intent = latest.notice_count > 0 and not as_of_sales
    evidence: list[str] = []
    if latest is not None:
        evidence.append(
            f"{latest.affiliate_count} affiliate Form 144 notice(s) on {latest.as_of} "
            f"for {ticker.upper()} ({latest.proposed_units:.0f} proposed units)."
        )
    if cluster:
        evidence.append(
            f"Frozen cluster rule hit: >={CLUSTER_MIN_AFFILIATES} distinct affiliates "
            f"inside {CLUSTER_WINDOW_DAYS} days."
        )
    if conflict:
        evidence.append("144 cluster without a same-day Form 4 sale (conflict radar).")
    if not scoped_notices:
        summary = "No eligible Form 144 notices are cached for this ticker."
        status = "unavailable"
        coverage = 0
        warnings = [summary]
    else:
        status = "radar"
        coverage = 100
        warnings = []
        summary = (
            "Form 144 intent radar is shadow-only. Proposed-sale clusters are not "
            "treated as bearish live signals and do not change recommendations."
        )
    return instantiate_sealed_shadow_view(
        Form144IntentView,
        {
            "mode": FORM144_MODE,
            "status": status,
            "score": 50,
            "modeled_impact": FORM144_MODELED_IMPACT,
            "applied_impact": FORM144_APPLIED_IMPACT,
            "coverage_score": coverage,
            "primary_source": PRIMARY_SOURCE,
            "cluster": cluster,
            "unmatched_intent": unmatched_intent,
            "conflict": conflict,
            "affiliate_count": 0 if latest is None else latest.affiliate_count,
            "proposed_units": 0.0 if latest is None else latest.proposed_units,
            "event_date": None if latest is None else latest.as_of,
            "summary": summary,
            "evidence": evidence,
            "warnings": warnings,
            "activation_gate": _activation_gate(),
            "as_of_date": as_of_date.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
            "lifecycle_label": LifecycleLabel.UNVERIFIED.value,
            "lifecycle_stage": LifecycleStage.CANDIDATE.value,
            "experiment_ids": (EXPERIMENT_FORM144,),
        },
        experiment_ids=(EXPERIMENT_FORM144,),
    )


def build_unavailable_form144_intent_view(message: str) -> Form144IntentView:
    return instantiate_sealed_shadow_view(
        Form144IntentView,
        {
            "mode": FORM144_MODE,
            "status": "unavailable",
            "score": None,
            "modeled_impact": FORM144_MODELED_IMPACT,
            "applied_impact": FORM144_APPLIED_IMPACT,
            "coverage_score": 0,
            "primary_source": PRIMARY_SOURCE,
            "cluster": False,
            "unmatched_intent": False,
            "conflict": False,
            "affiliate_count": 0,
            "proposed_units": 0.0,
            "event_date": None,
            "summary": message,
            "warnings": [message],
            "activation_gate": _activation_gate(),
            "updated_at": datetime.now(UTC).isoformat(),
            "lifecycle_label": LifecycleLabel.UNVERIFIED.value,
            "lifecycle_stage": LifecycleStage.CANDIDATE.value,
            "experiment_ids": (EXPERIMENT_FORM144,),
        },
        experiment_ids=(EXPERIMENT_FORM144,),
    )


def form144_intent_view_from_dict(payload: dict[str, Any] | None) -> Form144IntentView:
    if not isinstance(payload, dict):
        return build_unavailable_form144_intent_view(
            "The cached snapshot predates Form 144 intent radar."
        )
    return instantiate_sealed_shadow_view(
        Form144IntentView,
        dict(payload),
        experiment_ids=(EXPERIMENT_FORM144,),
    )


__all__ = [
    "Form144IntentView",
    "build_form144_intent_view",
    "build_unavailable_form144_intent_view",
    "form144_intent_view_from_dict",
]
