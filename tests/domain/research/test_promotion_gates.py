from __future__ import annotations

from dataclasses import replace

import pytest

from domain.recommendations.engine import write_live_recommendations
from domain.research.lifecycle import (
    EXPERIMENT_FINRA_SHORT_VOL,
    EXPERIMENT_FORM4,
    EXPERIMENT_GROUP_RS,
    EXPERIMENT_KCRORO_REGIME,
    EXPERIMENT_PEAD,
    FORBIDDEN_AUTO_PROMOTE,
    GATE_CHECKLIST,
    GateKind,
    GateReceipt,
    IN_FLIGHT_EXPERIMENT_IDS,
    LifecycleLabel,
    LifecycleStage,
    QUALIFIED_PLUS_STAGES,
    REQUIRED_LIVE_GATES,
    ShadowCandidate,
    derive_lifecycle_label,
    derive_lifecycle_stage,
    experiment_by_id,
    in_flight_experiments,
    is_qualified_plus,
    receipts_from_shadow_calibration,
)
from domain.research.promotion import (
    LIVE_SHADOW_PROMOTION_ENABLED,
    PromotionBlocked,
    apply_shadow_impact_to_score,
    evaluate_promotion,
    overlay_shadow_on_live_score,
    promote_shadow_candidate_to_live,
    seal_shadow_live_fields,
)
from domain.scoring.alternative_signals import build_unavailable_alternative_signal_view
from domain.scoring.earnings_intelligence import (
    build_unavailable_earnings_intelligence_view,
    earnings_intelligence_view_from_dict,
)
from domain.scoring.long_term import LongTermView
from domain.scoring.relative_strength import (
    build_unavailable_relative_strength_view,
    relative_strength_view_from_dict,
)
from domain.scoring.short_term import ShortTermView, TradeSetupView


def _receipt(gate: GateKind, *, passed: bool = True) -> GateReceipt:
    return GateReceipt(
        gate=gate,
        passed=passed,
        evidence=f"{gate.value} fixture",
        recorded_at="2026-09-14T00:00:00+00:00",
    )


def _complete_receipts() -> tuple[GateReceipt, ...]:
    return tuple(_receipt(gate) for gate in REQUIRED_LIVE_GATES)


def _candidate(**kwargs) -> ShadowCandidate:
    values = {
        "experiment_id": "group_rs",
        "modeled_impact": 8,
        "requested_applied_impact": 8,
    }
    values.update(kwargs)
    return ShadowCandidate(**values)


def _setup() -> TradeSetupView:
    return TradeSetupView(
        horizon_label="Swing",
        score=70,
        trade_state_label="WAIT FOR PULLBACK",
        trade_state_tone="watch",
        holding_period_label="5-15 days",
        setup_type="pullback",
        entry_price=100.0,
        target_price=110.0,
        stop_loss_price=95.0,
        explanation="fixture",
    )


def _short_view(score: int = 70) -> ShortTermView:
    setup = _setup()
    return ShortTermView(
        score=score,
        trend_direction="Bullish",
        trade_state_label="WAIT FOR PULLBACK",
        trade_state_tone="watch",
        trade_state_explanation="fixture",
        breakout_level=101.0,
        breakdown_level=99.0,
        is_actionable_now=False,
        setup_type="pullback",
        expected_holding_period="5-15 days",
        entry_idea="Wait for pullback",
        stop_loss_idea="Below structure",
        target_idea="Prior high",
        day_trade=setup,
        swing_trade=setup,
        primary_horizon_label="Swing",
    )


def test_in_flight_experiments_are_labeled_unverified_with_zero_live_impact() -> None:
    assert FORBIDDEN_AUTO_PROMOTE is True
    assert LIVE_SHADOW_PROMOTION_ENABLED is False
    assert IN_FLIGHT_EXPERIMENT_IDS == (
        EXPERIMENT_GROUP_RS,
        EXPERIMENT_PEAD,
        EXPERIMENT_FORM4,
        EXPERIMENT_FINRA_SHORT_VOL,
        EXPERIMENT_KCRORO_REGIME,
    )
    tagged = in_flight_experiments()
    assert {item.experiment_id for item in tagged} == set(IN_FLIGHT_EXPERIMENT_IDS)
    assert all(item.lifecycle_label is LifecycleLabel.UNVERIFIED for item in tagged)
    assert all(item.lifecycle_stage is LifecycleStage.CANDIDATE for item in tagged)
    assert all(item.live_applied_impact == 0 for item in tagged)
    assert experiment_by_id(EXPERIMENT_FINRA_SHORT_VOL).implemented is False


def test_gate_checklist_covers_the_required_live_set() -> None:
    assert tuple(item["gate"] for item in GATE_CHECKLIST) == tuple(
        gate.value for gate in REQUIRED_LIVE_GATES
    )
    assert QUALIFIED_PLUS_STAGES == {LifecycleStage.QUALIFIED, LifecycleStage.CHAMPION}


def test_promote_without_receipts_fails_closed() -> None:
    with pytest.raises(PromotionBlocked) as blocked:
        promote_shadow_candidate_to_live(_candidate(), human_authorized=True)

    assert "Missing required gate receipts" in str(blocked.value)
    assert any(
        gate.value in str(blocked.value) for gate in REQUIRED_LIVE_GATES
    )


def test_partial_receipts_fail_closed() -> None:
    candidate = _candidate(
        receipts=(_receipt(GateKind.OOS), _receipt(GateKind.WALK_FORWARD))
    )
    decision = evaluate_promotion(candidate, live_promotion_enabled=True)
    assert decision.allowed is False
    assert GateKind.MULTIPLE_TESTING in decision.missing_gates
    assert GateKind.FORWARD_PAPER in decision.missing_gates
    with pytest.raises(PromotionBlocked):
        promote_shadow_candidate_to_live(candidate, human_authorized=True)


def test_complete_receipts_do_not_auto_promote() -> None:
    candidate = _candidate(receipts=_complete_receipts())
    with pytest.raises(PromotionBlocked) as blocked:
        promote_shadow_candidate_to_live(candidate, human_authorized=False)

    assert "automatic promotion is forbidden" in str(blocked.value).lower()
    score, applied = apply_shadow_impact_to_score(70, 8, candidate)
    assert score == 70
    assert applied == 0
    assert derive_lifecycle_stage(candidate) is LifecycleStage.QUALIFIED
    assert is_qualified_plus(derive_lifecycle_stage(candidate)) is True


def test_explicit_human_promote_can_pass_only_when_live_switch_is_on() -> None:
    candidate = _candidate(receipts=_complete_receipts())
    promoted = promote_shadow_candidate_to_live(
        candidate,
        human_authorized=True,
        live_promotion_enabled=True,
    )
    assert promoted.human_authorized is True
    assert promoted.claimed_label is LifecycleLabel.REAL
    assert derive_lifecycle_stage(
        promoted,
        live_promotion_enabled=True,
    ) is LifecycleStage.CHAMPION
    score, applied = apply_shadow_impact_to_score(
        70,
        8,
        promoted,
        live_promotion_enabled=True,
    )
    assert applied == 8
    assert score == 78
    assert LIVE_SHADOW_PROMOTION_ENABLED is False


def test_human_authorization_still_fails_while_live_switch_is_off() -> None:
    candidate = _candidate(receipts=_complete_receipts())
    with pytest.raises(PromotionBlocked) as blocked:
        promote_shadow_candidate_to_live(
            candidate,
            human_authorized=True,
            live_promotion_enabled=False,
        )
    assert "readiness cannot enable live execution" in str(blocked.value).lower()
    assert derive_lifecycle_label(replace(candidate, human_authorized=True)) is LifecycleLabel.PAPER


def test_spoofed_real_label_does_not_authorize_a_live_write() -> None:
    candidate = _candidate(claimed_label=LifecycleLabel.REAL)
    score, applied = apply_shadow_impact_to_score(64, 10, candidate)
    assert score == 64
    assert applied == 0
    assert derive_lifecycle_label(candidate) is LifecycleLabel.UNVERIFIED


def test_demo_and_forward_paper_labels() -> None:
    demo = _candidate(data_source="demo")
    paper = _candidate(receipts=(_receipt(GateKind.FORWARD_PAPER),))
    assert derive_lifecycle_label(demo) is LifecycleLabel.DEMO
    assert derive_lifecycle_label(paper) is LifecycleLabel.PAPER


def test_live_recommendation_write_fails_closed_on_unauthorized_applied_impact() -> None:
    shadow = replace(
        build_unavailable_relative_strength_view(sector="Technology", message="fixture"),
        applied_impact=7,
        lifecycle_label=LifecycleLabel.REAL.value,
    )
    with pytest.raises(PromotionBlocked):
        write_live_recommendations(
            LongTermView(score=80, summary="fixture"),
            _short_view(),
            shadow_views=(shadow,),
        )


def test_unverified_zero_impact_write_does_not_change_live_labels() -> None:
    shadow = build_unavailable_relative_strength_view(sector="Technology", message="fixture")
    long_rec, short_rec = write_live_recommendations(
        LongTermView(score=80, summary="fixture"),
        _short_view(75),
        shadow_views=(shadow,),
    )
    assert shadow.applied_impact == 0
    assert shadow.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert long_rec.label == "Strong Buy"
    assert short_rec.label == "Strong Setup"


def test_overlay_and_seal_keep_unverified_impact_at_zero() -> None:
    long_view = LongTermView(score=60, summary="fixture")
    shadow = replace(
        build_unavailable_alternative_signal_view("fixture"),
        modeled_impact=8,
        score=90,
        status="constructive",
    )
    scored, sealed = overlay_shadow_on_live_score(long_view, shadow)
    assert sealed.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert sealed.lifecycle_stage == LifecycleStage.CANDIDATE.value
    assert EXPERIMENT_FORM4 in sealed.experiment_ids
    assert sealed.modeled_impact == 8
    assert sealed.applied_impact == 0
    assert scored.score == long_view.score

    spoofed = replace(
        shadow,
        applied_impact=9,
        lifecycle_label=LifecycleLabel.REAL.value,
        lifecycle_stage=LifecycleStage.CHAMPION.value,
    )
    sealed_spoof = seal_shadow_live_fields(spoofed)
    assert sealed_spoof.applied_impact == 0
    assert sealed_spoof.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert sealed_spoof.lifecycle_stage == LifecycleStage.CANDIDATE.value


def test_cache_rebuild_discards_spoofed_applied_impact() -> None:
    rs_payload = build_unavailable_relative_strength_view(
        sector="Technology",
        message="fixture",
    ).to_dict()
    rs_payload["applied_impact"] = 12
    rs_payload["lifecycle_label"] = "REAL"
    restored_rs = relative_strength_view_from_dict(rs_payload)
    assert restored_rs.applied_impact == 0
    assert restored_rs.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert restored_rs.lifecycle_stage == LifecycleStage.CANDIDATE.value
    assert restored_rs.experiment_ids == (EXPERIMENT_GROUP_RS,)

    ei_payload = build_unavailable_earnings_intelligence_view("fixture").to_dict()
    ei_payload["applied_impact"] = 4
    ei_payload["lifecycle_label"] = "REAL"
    restored_ei = earnings_intelligence_view_from_dict(ei_payload)
    assert restored_ei.applied_impact == 0
    assert restored_ei.lifecycle_label == LifecycleLabel.UNVERIFIED.value
    assert EXPERIMENT_PEAD in restored_ei.experiment_ids


def test_shadow_calibration_activation_does_not_issue_live_receipts() -> None:
    payload = {
        "requirements": {
            "minimum_resolved_signals": {"passed": True},
            "minimum_distinct_signal_dates": {"passed": True},
            "positive_directional_net_expectancy": {"passed": True},
            "average_coverage": {"passed": True},
            "positive_validation_folds": {"passed": True},
        }
    }
    receipts = receipts_from_shadow_calibration(payload)
    passed = {receipt.gate for receipt in receipts if receipt.passed}
    failed = {receipt.gate for receipt in receipts if not receipt.passed}
    assert passed == {GateKind.OOS, GateKind.WALK_FORWARD}
    assert failed == {GateKind.MULTIPLE_TESTING, GateKind.FORWARD_PAPER}
    assert all(receipt.rejection_evidence for receipt in receipts if not receipt.passed)
    candidate = ShadowCandidate(experiment_id="alternative_signals", receipts=receipts)
    decision = evaluate_promotion(candidate)
    assert decision.allowed is False
    assert decision.live_write_allowed is False
    assert decision.cannot_flip_live is True
    assert decision.qualified_plus is False
    assert decision.lifecycle_stage is LifecycleStage.OOS_VALIDATED
    assert decision.automatic_promotion is False
    assert GateKind.MULTIPLE_TESTING in decision.missing_gates
    assert GateKind.FORWARD_PAPER in decision.missing_gates
    assert decision.rejection_evidence
    assert any("multiple_testing" in item for item in decision.rejection_evidence)


def test_stages_progress_and_illegal_promote_below_qualified_fails() -> None:
    assert derive_lifecycle_stage(_candidate()) is LifecycleStage.CANDIDATE
    oos_only = _candidate(receipts=(_receipt(GateKind.OOS),))
    assert derive_lifecycle_stage(oos_only) is LifecycleStage.OOS_VALIDATED
    paper = _candidate(receipts=(_receipt(GateKind.FORWARD_PAPER),))
    assert derive_lifecycle_stage(paper) is LifecycleStage.FORWARD_PAPER
    assert is_qualified_plus(derive_lifecycle_stage(paper)) is False
    with pytest.raises(PromotionBlocked) as blocked:
        promote_shadow_candidate_to_live(
            paper,
            human_authorized=True,
            live_promotion_enabled=True,
        )
    assert "qualified+" in str(blocked.value).lower()
    decision = evaluate_promotion(oos_only)
    assert decision.rejection_evidence
    assert decision.cannot_flip_live is True


def test_readiness_cannot_flip_live_even_when_qualified() -> None:
    candidate = _candidate(receipts=_complete_receipts())
    decision = evaluate_promotion(candidate)
    assert decision.lifecycle_stage is LifecycleStage.QUALIFIED
    assert decision.qualified_plus is True
    assert decision.live_write_allowed is False
    assert decision.cannot_flip_live is True
    assert decision.release_mode == "paper_shadow"
    score, applied = apply_shadow_impact_to_score(70, 8, candidate)
    assert score == 70
    assert applied == 0
