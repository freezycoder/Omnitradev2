from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Mapping, Sequence, assert_never


class LifecycleLabel(str, Enum):
    """Provenance labels for shadow candidates and recommendation surfaces.

    REAL is never assigned by scanners. It can exist only after every live
    promotion gate has a passing receipt, the candidate is Qualified+, and
    an explicit human authorization that is still blocked by the hard-coded
    no-auto-promote switch.
    """

    REAL = "REAL"
    PAPER = "PAPER"
    DEMO = "DEMO"
    STALE = "STALE"
    UNVERIFIED = "UNVERIFIED"


class LifecycleStage(str, Enum):
    """OmniTrade research stages, adapted from the Candidate→Retired pattern.

    Names are local. This is process plumbing, not a copied claim set.
    Champion is unreachable while live promotion stays disabled.
    """

    CANDIDATE = "candidate"
    IN_SAMPLE = "in_sample"
    OOS_VALIDATED = "oos_validated"
    FORWARD_PAPER = "forward_paper"
    QUALIFIED = "qualified"
    CHAMPION = "champion"
    RETIRED = "retired"


class GateKind(str, Enum):
    OOS = "oos"
    WALK_FORWARD = "walk_forward"
    MULTIPLE_TESTING = "multiple_testing"
    FORWARD_PAPER = "forward_paper"


REQUIRED_LIVE_GATES: tuple[GateKind, ...] = (
    GateKind.OOS,
    GateKind.WALK_FORWARD,
    GateKind.MULTIPLE_TESTING,
    GateKind.FORWARD_PAPER,
)

FORBIDDEN_AUTO_PROMOTE = True
RELEASE_MODE_PAPER_SHADOW = "paper_shadow"

QUALIFIED_PLUS_STAGES: frozenset[LifecycleStage] = frozenset(
    {LifecycleStage.QUALIFIED, LifecycleStage.CHAMPION}
)

GATE_CHECKLIST: tuple[dict[str, str], ...] = (
    {
        "gate": GateKind.OOS.value,
        "requirement": (
            "Out-of-sample evidence: at least 50 resolved directional signals, "
            "12 distinct signal dates, positive net expectancy after costs, "
            "and average coverage of at least 70%."
        ),
        "blocks": "Any applied_impact or live recommendation contribution.",
    },
    {
        "gate": GateKind.WALK_FORWARD.value,
        "requirement": (
            "Walk-forward validation: at least two positive chronological "
            "folds with a calendar embargo; in-sample diagnostics never count."
        ),
        "blocks": "Any applied_impact or live recommendation contribution.",
    },
    {
        "gate": GateKind.MULTIPLE_TESTING.value,
        "requirement": (
            "Multiple-testing receipt: pre-registered family or hierarchical "
            "cluster bootstrap whose lower interval stays positive after "
            "neighbor-threshold stability. A single in-sample screen is not a receipt."
        ),
        "blocks": "Any applied_impact or live recommendation contribution.",
    },
    {
        "gate": GateKind.FORWARD_PAPER.value,
        "requirement": (
            "Forward-paper receipt: labeled PAPER live-forward tracking with "
            "recorded outcomes. Historical OOS is not a substitute."
        ),
        "blocks": "Any applied_impact or live recommendation contribution.",
    },
)


@dataclass(frozen=True)
class GateReceipt:
    gate: GateKind
    passed: bool
    evidence: str
    recorded_at: str | None = None
    rejection_evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.value,
            "passed": self.passed,
            "evidence": self.evidence,
            "recorded_at": self.recorded_at,
            "rejection_evidence": self.rejection_evidence,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | GateReceipt) -> "GateReceipt":
        if isinstance(payload, GateReceipt):
            return payload
        gate_value = str(payload.get("gate") or "").strip().lower()
        try:
            gate = GateKind(gate_value)
        except ValueError as exc:
            raise ValueError(f"Unknown promotion gate: {gate_value!r}") from exc
        passed = bool(payload.get("passed"))
        evidence = str(payload.get("evidence") or "")
        rejection = payload.get("rejection_evidence")
        rejection_evidence = None if passed else str(rejection or evidence or "") or None
        return cls(
            gate=gate,
            passed=passed,
            evidence=evidence,
            recorded_at=str(payload["recorded_at"]) if payload.get("recorded_at") else None,
            rejection_evidence=rejection_evidence,
        )


@dataclass(frozen=True)
class ShadowCandidate:
    experiment_id: str
    receipts: tuple[GateReceipt, ...] = ()
    modeled_impact: int = 0
    requested_applied_impact: int = 0
    data_source: str | None = None
    claimed_label: LifecycleLabel = LifecycleLabel.UNVERIFIED
    human_authorized: bool = False
    stale: bool = False
    experiment_ids: tuple[str, ...] = ()

    @property
    def passed_gates(self) -> frozenset[GateKind]:
        return frozenset(receipt.gate for receipt in self.receipts if receipt.passed)

    @property
    def missing_gates(self) -> tuple[GateKind, ...]:
        passed = self.passed_gates
        return tuple(gate for gate in REQUIRED_LIVE_GATES if gate not in passed)

    def has_all_required_receipts(self) -> bool:
        return not self.missing_gates

    def rejection_evidence(self) -> tuple[str, ...]:
        items: list[str] = []
        for receipt in self.receipts:
            if receipt.passed:
                continue
            text = receipt.rejection_evidence or receipt.evidence
            if text:
                items.append(f"{receipt.gate.value}: {text}")
        for gate in self.missing_gates:
            if any(receipt.gate is gate for receipt in self.receipts):
                continue
            items.append(f"{gate.value}: No receipt recorded.")
        return tuple(items)


@dataclass(frozen=True)
class ShadowExperiment:
    experiment_id: str
    name: str
    plumbing: str
    implemented: bool
    lifecycle_label: LifecycleLabel = LifecycleLabel.UNVERIFIED
    lifecycle_stage: LifecycleStage = LifecycleStage.CANDIDATE
    live_applied_impact: int = 0
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "plumbing": self.plumbing,
            "implemented": self.implemented,
            "lifecycle_label": self.lifecycle_label.value,
            "lifecycle_stage": self.lifecycle_stage.value,
            "live_applied_impact": self.live_applied_impact,
            "notes": self.notes,
            "automatic_promotion": False,
            "release_mode": RELEASE_MODE_PAPER_SHADOW,
        }


EXPERIMENT_ALTERNATIVE_SIGNALS = "alternative_signals"
EXPERIMENT_GROUP_RS = "group_rs"
EXPERIMENT_PEAD = "pead"
EXPERIMENT_FORM4 = "form4"
EXPERIMENT_FORM144 = "form144"
EXPERIMENT_FINRA_SHORT_VOL = "finra_short_vol"
EXPERIMENT_EARNINGS_INTELLIGENCE = "earnings_intelligence"

EXPERIMENTS: tuple[ShadowExperiment, ...] = (
    ShadowExperiment(
        experiment_id=EXPERIMENT_ALTERNATIVE_SIGNALS,
        name="SEC / classified-news / FRED overlay",
        plumbing="domain.scoring.alternative_signals",
        implemented=True,
        notes="Existing shadow overlay. Modeled impact is recorded; applied impact stays 0.",
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_GROUP_RS,
        name="Group relative strength",
        plumbing="domain.scoring.relative_strength",
        implemented=True,
        notes="Universe and sector RS percentiles. Existing shadow RS layer; live score unchanged.",
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_PEAD,
        name="Post-earnings announcement drift (filing 3d)",
        plumbing="domain.scoring.earnings_intelligence.post_filing_3d_return_pct",
        implemented=True,
        notes="Observed three-session move after the latest SEC earnings filing. Shadow-only.",
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_FORM4,
        name="Form 4 open-market insider flow",
        plumbing="providers.events.sec_edgar_client / alternative_signals.sec_events",
        implemented=True,
        notes="Form 4 open-market insider transactions already feed the SEC shadow component.",
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_FORM144,
        name="Form 144 proposed-sale intent radar",
        plumbing="domain.research.form144_match_study / domain.scoring.form144_intent",
        implemented=True,
        notes=(
            "Shadow-only Form 144 XML ingest, frozen N/W clusters, and 144→Form4 match "
            "study. Not an alpha overlay and not a JoF-grade CAR claim. applied_impact stays 0."
        ),
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_FINRA_SHORT_VOL,
        name="FINRA short-volume overlay",
        plumbing="unregistered-signal",
        implemented=False,
        notes=(
            "Registered as an UNVERIFIED in-flight candidate only. No FINRA short-volume "
            "signal is implemented and no live recommendation path exists."
        ),
    ),
    ShadowExperiment(
        experiment_id=EXPERIMENT_EARNINGS_INTELLIGENCE,
        name="Earnings intelligence overlay",
        plumbing="domain.scoring.earnings_intelligence",
        implemented=True,
        notes="Existing earnings-intelligence shadow layer, including PEAD filing-window evidence.",
    ),
)

IN_FLIGHT_EXPERIMENT_IDS: tuple[str, ...] = (
    EXPERIMENT_GROUP_RS,
    EXPERIMENT_PEAD,
    EXPERIMENT_FORM4,
    EXPERIMENT_FORM144,
    EXPERIMENT_FINRA_SHORT_VOL,
)


def experiment_by_id(experiment_id: str) -> ShadowExperiment:
    for experiment in EXPERIMENTS:
        if experiment.experiment_id == experiment_id:
            return experiment
    raise KeyError(experiment_id)


def in_flight_experiments() -> tuple[ShadowExperiment, ...]:
    return tuple(experiment_by_id(experiment_id) for experiment_id in IN_FLIGHT_EXPERIMENT_IDS)


def parse_lifecycle_label(value: Any) -> LifecycleLabel:
    if isinstance(value, LifecycleLabel):
        match value:
            case (
                LifecycleLabel.REAL
                | LifecycleLabel.PAPER
                | LifecycleLabel.DEMO
                | LifecycleLabel.STALE
                | LifecycleLabel.UNVERIFIED
            ):
                return value
            case _:
                assert_never(value)
    raw = str(value or LifecycleLabel.UNVERIFIED.value).strip().upper()
    try:
        label = LifecycleLabel(raw)
    except ValueError:
        return LifecycleLabel.UNVERIFIED
    match label:
        case (
            LifecycleLabel.REAL
            | LifecycleLabel.PAPER
            | LifecycleLabel.DEMO
            | LifecycleLabel.STALE
            | LifecycleLabel.UNVERIFIED
        ):
            return label
        case _:
            assert_never(label)


def parse_lifecycle_stage(value: Any) -> LifecycleStage:
    if isinstance(value, LifecycleStage):
        match value:
            case (
                LifecycleStage.CANDIDATE
                | LifecycleStage.IN_SAMPLE
                | LifecycleStage.OOS_VALIDATED
                | LifecycleStage.FORWARD_PAPER
                | LifecycleStage.QUALIFIED
                | LifecycleStage.CHAMPION
                | LifecycleStage.RETIRED
            ):
                return value
            case _:
                assert_never(value)
    raw = str(value or LifecycleStage.CANDIDATE.value).strip().lower()
    try:
        stage = LifecycleStage(raw)
    except ValueError:
        return LifecycleStage.CANDIDATE
    match stage:
        case (
            LifecycleStage.CANDIDATE
            | LifecycleStage.IN_SAMPLE
            | LifecycleStage.OOS_VALIDATED
            | LifecycleStage.FORWARD_PAPER
            | LifecycleStage.QUALIFIED
            | LifecycleStage.CHAMPION
            | LifecycleStage.RETIRED
        ):
            return stage
        case _:
            assert_never(stage)


def is_qualified_plus(stage: LifecycleStage) -> bool:
    match stage:
        case LifecycleStage.QUALIFIED | LifecycleStage.CHAMPION:
            return True
        case (
            LifecycleStage.CANDIDATE
            | LifecycleStage.IN_SAMPLE
            | LifecycleStage.OOS_VALIDATED
            | LifecycleStage.FORWARD_PAPER
            | LifecycleStage.RETIRED
        ):
            return False
        case _:
            assert_never(stage)


def derive_lifecycle_label(
    candidate: ShadowCandidate,
    *,
    live_promotion_enabled: bool = False,
) -> LifecycleLabel:
    """Derive the enforceable label. Claimed REAL without receipts is ignored."""
    source = (candidate.data_source or "").strip().lower()
    if source == "demo":
        return LifecycleLabel.DEMO
    if candidate.stale or source in {"unavailable", "stale"}:
        return LifecycleLabel.STALE
    stage = derive_lifecycle_stage(
        candidate,
        live_promotion_enabled=live_promotion_enabled,
    )
    match stage:
        case LifecycleStage.CHAMPION:
            return LifecycleLabel.REAL
        case LifecycleStage.FORWARD_PAPER | LifecycleStage.QUALIFIED:
            return LifecycleLabel.PAPER
        case LifecycleStage.RETIRED:
            return LifecycleLabel.STALE
        case (
            LifecycleStage.CANDIDATE
            | LifecycleStage.IN_SAMPLE
            | LifecycleStage.OOS_VALIDATED
        ):
            return LifecycleLabel.UNVERIFIED
        case _:
            assert_never(stage)


def derive_lifecycle_stage(
    candidate: ShadowCandidate,
    *,
    live_promotion_enabled: bool = False,
) -> LifecycleStage:
    source = (candidate.data_source or "").strip().lower()
    if candidate.stale or source in {"unavailable", "stale"}:
        return LifecycleStage.RETIRED
    if candidate.has_all_required_receipts():
        if candidate.human_authorized and live_promotion_enabled:
            return LifecycleStage.CHAMPION
        return LifecycleStage.QUALIFIED
    passed = candidate.passed_gates
    if GateKind.FORWARD_PAPER in passed:
        return LifecycleStage.FORWARD_PAPER
    if GateKind.OOS in passed:
        return LifecycleStage.OOS_VALIDATED
    if candidate.receipts:
        return LifecycleStage.IN_SAMPLE
    return LifecycleStage.CANDIDATE


def _requirement_passed(payload: Mapping[str, Any], key: str) -> bool:
    requirement = payload.get("requirements")
    if not isinstance(requirement, Mapping):
        return False
    item = requirement.get(key)
    if not isinstance(item, Mapping):
        return False
    return bool(item.get("passed"))


def receipts_from_shadow_calibration(payload: Mapping[str, Any]) -> tuple[GateReceipt, ...]:
    """Map existing shadow calibration payloads onto OOS / walk-forward receipts.

    Multiple-testing and forward-paper receipts are never inferred from
    activation_ready. Failed gates are stored as rejection evidence.
    Passing today's evidence gates is not a live-promotion receipt.
    """

    recorded_at = datetime.now(UTC).isoformat()
    oos_passed = all(
        _requirement_passed(payload, key)
        for key in (
            "minimum_resolved_signals",
            "minimum_distinct_signal_dates",
            "positive_directional_net_expectancy",
            "average_coverage",
        )
    )
    walk_forward_passed = _requirement_passed(payload, "positive_validation_folds")
    oos_evidence = (
        "Calibration OOS cohort met resolved-signal, date, expectancy, and coverage floors."
        if oos_passed
        else "Calibration OOS cohort has not met the evidence floors."
    )
    walk_forward_evidence = (
        "Calibration recorded at least two positive chronological validation folds."
        if walk_forward_passed
        else "Walk-forward folds have not met the positive-fold requirement."
    )
    multiple_testing_evidence = (
        "Multiple-testing control was not pre-registered. "
        "activation_ready and in-sample screens are not a substitute."
    )
    forward_paper_evidence = (
        "No forward-paper period receipt. Historical OOS is not a substitute "
        "for labeled PAPER live-forward tracking."
    )
    return (
        GateReceipt(
            gate=GateKind.OOS,
            passed=oos_passed,
            evidence=oos_evidence,
            recorded_at=recorded_at,
            rejection_evidence=None if oos_passed else oos_evidence,
        ),
        GateReceipt(
            gate=GateKind.WALK_FORWARD,
            passed=walk_forward_passed,
            evidence=walk_forward_evidence,
            recorded_at=recorded_at,
            rejection_evidence=None if walk_forward_passed else walk_forward_evidence,
        ),
        GateReceipt(
            gate=GateKind.MULTIPLE_TESTING,
            passed=False,
            evidence=multiple_testing_evidence,
            recorded_at=recorded_at,
            rejection_evidence=multiple_testing_evidence,
        ),
        GateReceipt(
            gate=GateKind.FORWARD_PAPER,
            passed=False,
            evidence=forward_paper_evidence,
            recorded_at=recorded_at,
            rejection_evidence=forward_paper_evidence,
        ),
    )


def default_experiment_ids(*experiment_ids: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(experiment_ids))


def default_shadow_state(*experiment_ids: str) -> dict[str, Any]:
    return {
        "lifecycle_label": LifecycleLabel.UNVERIFIED.value,
        "lifecycle_stage": LifecycleStage.CANDIDATE.value,
        "experiment_ids": default_experiment_ids(*experiment_ids),
        "promotion_receipts": (),
    }


def coerce_experiment_ids(value: Any, fallback: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        ids = tuple(str(item).strip() for item in value if str(item).strip())
        if ids:
            return ids
    return tuple(fallback)


def coerce_receipts(value: Any) -> tuple[GateReceipt, ...]:
    if not value:
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return tuple(GateReceipt.from_mapping(item) for item in value if item)
    return ()


def receipt_dicts(receipts: Sequence[GateReceipt]) -> tuple[dict[str, Any], ...]:
    return tuple(receipt.to_dict() for receipt in receipts)


__all__ = [
    "EXPERIMENT_ALTERNATIVE_SIGNALS",
    "EXPERIMENT_EARNINGS_INTELLIGENCE",
    "EXPERIMENT_FINRA_SHORT_VOL",
    "EXPERIMENT_FORM4",
    "EXPERIMENT_FORM144",
    "EXPERIMENT_GROUP_RS",
    "EXPERIMENT_PEAD",
    "EXPERIMENTS",
    "FORBIDDEN_AUTO_PROMOTE",
    "GATE_CHECKLIST",
    "GateKind",
    "GateReceipt",
    "IN_FLIGHT_EXPERIMENT_IDS",
    "LifecycleLabel",
    "LifecycleStage",
    "QUALIFIED_PLUS_STAGES",
    "RELEASE_MODE_PAPER_SHADOW",
    "REQUIRED_LIVE_GATES",
    "ShadowCandidate",
    "ShadowExperiment",
    "coerce_experiment_ids",
    "coerce_receipts",
    "default_experiment_ids",
    "default_shadow_state",
    "derive_lifecycle_label",
    "derive_lifecycle_stage",
    "experiment_by_id",
    "in_flight_experiments",
    "is_qualified_plus",
    "parse_lifecycle_label",
    "parse_lifecycle_stage",
    "receipt_dicts",
    "receipts_from_shadow_calibration",
]
