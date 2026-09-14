from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Iterable, Sequence, TypeVar

from domain.research.lifecycle import (
    GateKind,
    GateReceipt,
    LifecycleLabel,
    ShadowCandidate,
    coerce_experiment_ids,
    coerce_receipts,
    derive_lifecycle_label,
    parse_lifecycle_label,
    receipt_dicts,
    receipts_from_shadow_calibration,
)


LIVE_SHADOW_PROMOTION_ENABLED = False

ScoreViewT = TypeVar("ScoreViewT")
ShadowViewT = TypeVar("ShadowViewT")


class PromotionBlocked(RuntimeError):
    """Raised when a shadow candidate is refused a live-recommendation write."""

    def __init__(self, reasons: Sequence[str], *, decision: "PromotionDecision | None" = None) -> None:
        self.reasons = tuple(reasons)
        self.decision = decision
        message = "; ".join(self.reasons) if self.reasons else "Live promotion is blocked."
        super().__init__(message)


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    lifecycle_label: LifecycleLabel
    automatic_promotion: bool
    live_write_allowed: bool
    missing_gates: tuple[GateKind, ...]
    reasons: tuple[str, ...]
    receipts: tuple[GateReceipt, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "lifecycle_label": self.lifecycle_label.value,
            "automatic_promotion": self.automatic_promotion,
            "live_write_allowed": self.live_write_allowed,
            "missing_gates": [gate.value for gate in self.missing_gates],
            "reasons": list(self.reasons),
            "receipts": [receipt.to_dict() for receipt in self.receipts],
        }


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def evaluate_promotion(
    candidate: ShadowCandidate,
    *,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> PromotionDecision:
    missing = candidate.missing_gates
    reasons: list[str] = []
    if missing:
        reasons.append(
            "Missing required gate receipts: "
            + ", ".join(gate.value for gate in missing)
            + "."
        )
    if not candidate.human_authorized:
        reasons.append("Human authorization is required; automatic promotion is forbidden.")
    if not live_promotion_enabled:
        reasons.append("Live shadow promotion is disabled; readiness cannot enable live execution.")

    allowed = not reasons
    lifecycle_label = derive_lifecycle_label(
        candidate,
        live_promotion_enabled=live_promotion_enabled,
    )
    return PromotionDecision(
        allowed=allowed,
        lifecycle_label=lifecycle_label,
        automatic_promotion=False,
        live_write_allowed=allowed,
        missing_gates=missing,
        reasons=tuple(reasons),
        receipts=candidate.receipts,
    )


def authorize_live_shadow_write(
    candidate: ShadowCandidate,
    *,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> PromotionDecision:
    decision = evaluate_promotion(
        candidate,
        live_promotion_enabled=live_promotion_enabled,
    )
    if not decision.allowed:
        raise PromotionBlocked(decision.reasons, decision=decision)
    return decision


def apply_shadow_impact_to_score(
    base_score: int,
    modeled_impact: int,
    candidate: ShadowCandidate,
    *,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> tuple[int, int]:
    """Return ``(live_score, applied_impact)``.

    Fail closed: applied impact stays 0 unless every receipt, human
    authorization, and the live-promotion switch are present. Production
    keeps the switch off, so this never mutates live scores.
    """

    try:
        authorize_live_shadow_write(
            candidate,
            live_promotion_enabled=live_promotion_enabled,
        )
    except PromotionBlocked:
        return int(base_score), 0
    applied = int(modeled_impact)
    return _clamp_score(int(base_score) + applied), applied


def overlay_shadow_on_live_score(
    view: ScoreViewT,
    shadow_view: ShadowViewT,
    *,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> tuple[ScoreViewT, ShadowViewT]:
    """Attempt to apply a shadow overlay onto a live score view.

    Without receipts this is a no-op: the live score is unchanged and
    ``applied_impact`` on the shadow view is forced to 0.
    """

    base_score = int(getattr(view, "score"))
    modeled_impact = int(getattr(shadow_view, "modeled_impact", 0) or 0)
    candidate = candidate_from_view(shadow_view)
    new_score, applied = apply_shadow_impact_to_score(
        base_score,
        modeled_impact,
        candidate,
        live_promotion_enabled=live_promotion_enabled,
    )
    sealed_shadow = replace(
        shadow_view,
        applied_impact=applied,
        lifecycle_label=derive_lifecycle_label(
            candidate,
            live_promotion_enabled=live_promotion_enabled,
        ).value,
    )
    if applied == 0 or new_score == base_score:
        return view, sealed_shadow
    return replace(view, score=new_score), sealed_shadow


def promote_shadow_candidate_to_live(
    candidate: ShadowCandidate,
    *,
    human_authorized: bool = False,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> ShadowCandidate:
    """Explicit promotion entry point. Never auto-promotes.

    Even a fully receipted challenger stays blocked unless a human sets
    ``human_authorized=True`` *and* the hard live-promotion switch is on.
    The switch stays off; this function exists so tests can prove fail-closed.
    """

    authorized = replace(candidate, human_authorized=bool(human_authorized))
    authorize_live_shadow_write(
        authorized,
        live_promotion_enabled=live_promotion_enabled,
    )
    return replace(
        authorized,
        claimed_label=LifecycleLabel.REAL,
        requested_applied_impact=int(authorized.modeled_impact),
    )


def assert_live_recommendation_write_allowed(
    shadow_views: Iterable[Any],
    *,
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> None:
    """Choke point for paths that write live recommendation labels.

    Unverified candidates with ``applied_impact == 0`` are allowed through
    (no live behavior change). Any non-zero applied impact must pass every
    promotion gate; otherwise the write fails closed.
    """

    for view in shadow_views:
        if view is None:
            continue
        applied = int(getattr(view, "applied_impact", 0) or 0)
        if applied == 0:
            continue
        candidate = candidate_from_view(view)
        authorize_live_shadow_write(
            candidate,
            live_promotion_enabled=live_promotion_enabled,
        )


def candidate_from_view(
    view: Any,
    *,
    data_source: str | None = None,
    experiment_ids: Sequence[str] = (),
) -> ShadowCandidate:
    ids = coerce_experiment_ids(
        getattr(view, "experiment_ids", None),
        experiment_ids,
    )
    receipts = coerce_receipts(getattr(view, "promotion_receipts", ()))
    claimed = parse_lifecycle_label(getattr(view, "lifecycle_label", None))
    source = data_source if data_source is not None else getattr(view, "data_source", None)
    return ShadowCandidate(
        experiment_id=ids[0] if ids else "unknown",
        experiment_ids=ids,
        receipts=receipts,
        modeled_impact=int(getattr(view, "modeled_impact", 0) or 0),
        requested_applied_impact=int(getattr(view, "applied_impact", 0) or 0),
        data_source=str(source) if source else None,
        claimed_label=claimed,
        human_authorized=False,
        stale=claimed is LifecycleLabel.STALE,
    )


def seal_shadow_live_fields(
    view: ShadowViewT,
    *,
    data_source: str | None = None,
    experiment_ids: Sequence[str] = (),
    live_promotion_enabled: bool = LIVE_SHADOW_PROMOTION_ENABLED,
) -> ShadowViewT:
    """Force live-safe fields onto a shadow view.

    Spoofed REAL labels and non-zero ``applied_impact`` values are discarded
    unless promotion is fully authorized (which production never is).
    """

    candidate = candidate_from_view(
        view,
        data_source=data_source,
        experiment_ids=experiment_ids,
    )
    applied = 0
    try:
        authorize_live_shadow_write(
            candidate,
            live_promotion_enabled=live_promotion_enabled,
        )
        applied = int(candidate.requested_applied_impact or candidate.modeled_impact)
    except PromotionBlocked:
        applied = 0
    updates: dict[str, Any] = {
        "applied_impact": applied,
        "lifecycle_label": derive_lifecycle_label(
            candidate,
            live_promotion_enabled=live_promotion_enabled,
        ).value,
    }
    if hasattr(view, "experiment_ids") and candidate.experiment_ids:
        updates["experiment_ids"] = candidate.experiment_ids
    if hasattr(view, "promotion_receipts"):
        updates["promotion_receipts"] = receipt_dicts(candidate.receipts)
    return replace(view, **updates)


def instantiate_sealed_shadow_view(
    view_cls: type[ShadowViewT],
    values: dict[str, Any],
    *,
    experiment_ids: Sequence[str],
    data_source: str | None = None,
) -> ShadowViewT:
    prepared = dict(values)
    prepared["experiment_ids"] = coerce_experiment_ids(
        prepared.get("experiment_ids"),
        experiment_ids,
    )
    prepared["promotion_receipts"] = receipt_dicts(
        coerce_receipts(prepared.get("promotion_receipts"))
    )
    prepared["lifecycle_label"] = parse_lifecycle_label(
        prepared.get("lifecycle_label")
    ).value
    allowed = {item.name for item in fields(view_cls)}
    view = view_cls(**{key: value for key, value in prepared.items() if key in allowed})
    return seal_shadow_live_fields(
        view,
        data_source=data_source,
        experiment_ids=experiment_ids,
    )


def annotate_calibration_payload(
    payload: dict[str, Any],
    *,
    experiment_id: str,
) -> dict[str, Any]:
    receipts = receipts_from_shadow_calibration(payload)
    candidate = ShadowCandidate(experiment_id=experiment_id, receipts=receipts)
    decision = evaluate_promotion(candidate)
    annotated = dict(payload)
    annotated["lifecycle_label"] = decision.lifecycle_label.value
    annotated["promotion"] = decision.to_dict()
    annotated["automatic_activation"] = False
    return annotated


__all__ = [
    "LIVE_SHADOW_PROMOTION_ENABLED",
    "PromotionBlocked",
    "PromotionDecision",
    "annotate_calibration_payload",
    "apply_shadow_impact_to_score",
    "assert_live_recommendation_write_allowed",
    "authorize_live_shadow_write",
    "candidate_from_view",
    "evaluate_promotion",
    "instantiate_sealed_shadow_view",
    "overlay_shadow_on_live_score",
    "promote_shadow_candidate_to_live",
    "seal_shadow_live_fields",
]
