from __future__ import annotations

from pathlib import Path

from config.form144 import (
    CLUSTER_MIN_AFFILIATES,
    CLUSTER_WINDOW_DAYS,
    FORM144_APPLIED_IMPACT,
    MATCH_RATE_FLOOR,
    MATCH_WINDOW_DAYS,
    PRIMARY_SOURCE,
)
from domain.research.form144_features import classify_affiliate, detect_clusters, ticker_day_intensity
from domain.research.form144_fixture import aligned_form144_inputs, evaluate_aligned_fixture
from domain.scoring.form144_intent import build_form144_intent_view
from providers.events.form144_models import ProposedSaleNotice


def test_protocol_is_frozen_before_eval() -> None:
    assert CLUSTER_MIN_AFFILIATES == 3
    assert CLUSTER_WINDOW_DAYS == 5
    assert MATCH_WINDOW_DAYS == 10
    assert MATCH_RATE_FLOOR == 0.40
    assert FORM144_APPLIED_IMPACT == 0
    assert PRIMARY_SOURCE.startswith("edgar_form144")


def test_cluster_requires_three_affiliates_inside_frozen_window() -> None:
    notices, _sales, _panel = aligned_form144_inputs(mode="lead")
    clusters = detect_clusters(notices)
    assert clusters
    assert all(event.affiliate_count >= CLUSTER_MIN_AFFILIATES for event in clusters)
    intensities = ticker_day_intensity(notices)
    assert any(row.cluster for row in intensities)


def test_issuer_self_filing_is_excluded() -> None:
    notice = ProposedSaleNotice(
        accession_number="self",
        ticker="AAA",
        issuer_cik="0000320193",
        issuer_name="Issuer",
        filer_cik="0000320193",
        filer_name="Issuer",
        relationship=None,
        filed_at="2023-03-15",
        approx_sale_date="2023-03-15",
        proposed_units=1000.0,
        aggregate_market_value=None,
        broker=None,
        prior_3m_units=None,
        prior_3m_proceeds=None,
        securities_class=None,
        source="fixture",
    )
    eligible, reason = classify_affiliate(notice)
    assert eligible is False
    assert reason == "issuer_self_filing"


def test_lead_fixture_matches_and_shows_nested_lift() -> None:
    payload = evaluate_aligned_fixture(mode="lead")
    assert payload["status"] == "shadow_research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == 0
    assert payload["alpha_claim"] is False
    assert payload["jof_car_claim"] is False
    assert payload["match_study"]["floor_met"] is True
    assert payload["match_study"]["match_rate"] >= MATCH_RATE_FLOOR
    assert payload["nested_model"]["positive_folds"] >= 2
    assert payload["verdict"] == "SUCCESS"
    assert payload["classification"] == "shadow_calibration"
    assert payload["optional_drift"]["used_for_verdict"] is False
    assert payload["optional_drift"]["label"] == "descriptive_only_not_car_not_alpha"


def test_same_day_execution_is_infra_not_alpha() -> None:
    payload = evaluate_aligned_fixture(mode="same_day")
    assert payload["match_study"]["floor_met"] is True
    assert payload["nested_model"]["incremental_lift"] is False
    assert payload["verdict"] == "SUCCESS_INFRA"
    assert payload["classification"] == "infra_conflict_radar"
    assert payload["alpha_claim"] is False


def test_unmatched_book_fails_match_floor() -> None:
    payload = evaluate_aligned_fixture(mode="unmatched")
    assert payload["verdict"] == "FAIL"
    assert payload["match_study"]["floor_met"] is False
    assert payload["match_study"]["match_rate"] < MATCH_RATE_FLOOR


def test_shadow_view_never_applies_live_or_bearish_impact() -> None:
    notices, sales, _panel = aligned_form144_inputs(mode="lead")
    view = build_form144_intent_view(
        ticker="AAA",
        notices=notices,
        sales=sales,
        as_of="2023-06-01",
    )
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.modeled_impact == 0
    assert view.cluster is True
    assert view.activation_gate["live_recommendation_changes"] is False
    assert view.activation_gate["alpha_claim"] is False
    assert view.experiment_ids == ("form144",)


def test_recommendation_engine_does_not_import_form144() -> None:
    engine = Path("domain/recommendations/engine.py").read_text(encoding="utf-8")
    alt = Path("domain/scoring/alternative_signals.py").read_text(encoding="utf-8")
    ticker = Path("application/ticker_service.py").read_text(encoding="utf-8")
    assert "form144" not in engine
    assert "form144" not in alt
    assert "form144" not in ticker
