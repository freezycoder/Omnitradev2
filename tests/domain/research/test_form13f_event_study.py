from __future__ import annotations

from pathlib import Path

from config.form13f import (
    CLUSTER_MIN_NOTABLE_MANAGERS,
    FORM13F_APPLIED_IMPACT,
    PRIMARY_SOURCE,
    TAXONOMY_VERSION,
)
from domain.research.form13f_event_study import evaluate_form13f_experiment
from domain.research.form13f_features import detect_clusters, primary_cluster_events
from domain.research.form13f_fixture import aligned_form13f_inputs, evaluate_aligned_fixture
from domain.scoring.form13f_cluster import build_form13f_cluster_view


def test_protocol_is_frozen_before_eval() -> None:
    assert TAXONOMY_VERSION == "v1"
    assert CLUSTER_MIN_NOTABLE_MANAGERS == 3
    assert FORM13F_APPLIED_IMPACT == 0
    assert PRIMARY_SOURCE.startswith("sec")


def test_aligned_cluster_entry_passes_walk_forward() -> None:
    payload = evaluate_aligned_fixture(with_burst=True)
    assert payload["status"] == "shadow_research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == 0
    assert payload["verdict"] == "SUCCESS"
    assert payload["positive_folds"] >= 2
    assert payload["protocol"]["cluster_k"] == 3
    primary_rows = [row for row in payload["event_rows"] if row["primary_book"] == 1]
    assert primary_rows
    assert all(row["lag_correct"] for row in primary_rows)
    assert all(row["event_date"] != row["reportable_quarter"] for row in primary_rows)
    assert payload["etf_churn"]["suspect_cluster_entries"] > 0
    assert payload["etf_churn"]["primary_book_after_filter"] == len(primary_rows)


def test_no_excess_after_match_fails() -> None:
    payload = evaluate_aligned_fixture(with_burst=False)
    assert payload["verdict"] in {"FAIL", "INCONCLUSIVE"}
    if payload["verdict"] == "FAIL":
        assert payload["positive_folds"] < 2


def test_etf_churn_is_removed_from_primary_book() -> None:
    holdings, _panel = aligned_form13f_inputs(with_burst=True)
    clusters = detect_clusters(holdings)
    primary = primary_cluster_events(clusters)
    assert {event.ticker for event in primary} <= {"AAA", "ZZZ", "YYY"}
    assert any(event.ticker == "CCC" and event.etf_churn_suspect for event in clusters)


def test_shadow_view_never_applies_live_impact() -> None:
    holdings, _panel = aligned_form13f_inputs(with_burst=True)
    view = build_form13f_cluster_view(ticker="AAA", holdings=holdings, as_of="2022-05-31")
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.cluster_entry is True
    assert view.modeled_impact > 0
    assert view.activation_gate["live_recommendation_changes"] is False


def test_recommendation_engine_does_not_import_form13f() -> None:
    engine = Path("domain/recommendations/engine.py").read_text(encoding="utf-8")
    alt = Path("domain/scoring/alternative_signals.py").read_text(encoding="utf-8")
    assert "form13f" not in engine
    assert "form13f" not in alt
