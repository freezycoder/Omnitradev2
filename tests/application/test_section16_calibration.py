from __future__ import annotations

import json
from datetime import date, timedelta

from application.calibration_service import CalibrationService
from application.scan_service import _rank_results, _section16_insider_fields
from domain.scoring.section16_insider import build_unavailable_section16_insider_view


class _OutcomeRepository:
    def __init__(self, rows):
        self._rows = rows

    def list_calibration_observations(self):
        return self._rows

    @staticmethod
    def _rows_to_expectancy_stats(rows):
        from storage.repositories.outcome_repository import OutcomeRepository

        return OutcomeRepository._rows_to_expectancy_stats(rows)


def _row(index: int, impact: int, realized_return: float, *, cluster: bool = False):
    created = date(2026, 1, 1) + timedelta(days=index)
    return {
        "signal_id": f"signal-{index}",
        "ticker": f"T{index % 10}",
        "created_at": created.isoformat(),
        "realized_return_pct": realized_return,
        "feature_snapshot_json": json.dumps(
            {
                "section16_insider": {
                    "score": 50 + impact * 5,
                    "modeled_impact": impact,
                    "applied_impact": 0,
                    "coverage_score": 100,
                    "cluster_flag": cluster,
                }
            }
        ),
    }


def test_section16_calibration_stays_locked_and_shadow_only():
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository(
        [_row(index, 2 if index % 2 == 0 else -2, 1.0 if index % 2 == 0 else -1.0) for index in range(20)]
    )

    payload = service.get_section16_insider_analysis()

    assert payload["mode"] == "shadow"
    assert payload["automatic_activation"] is False
    assert payload["activation_ready"] is False
    assert payload["requirements"]["zero_live_applied_impact"]["passed"] is True
    assert payload["protocol"]["open_market_codes"] == ["P", "S"]
    assert payload["protocol"]["cluster_rule"]["min_distinct_insiders"] == 3
    assert payload["protocol"]["overlap_enrichment_threshold_pct"] == 70.0


def test_section16_calibration_rewards_aligned_buy_cohorts():
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository(
        [
            _row(
                index,
                3 if index % 2 == 0 else -2,
                1.2 if index % 2 == 0 else -1.0,
                cluster=index % 2 == 0,
            )
            for index in range(60)
        ]
    )

    payload = service.get_section16_insider_analysis()

    assert payload["directional_resolved_signals"] == 60
    assert payload["directional_net_expectancy_pct"] > 0
    assert payload["requirements"]["minimum_resolved_signals"]["passed"] is True
    assert {row["section16_band"] for row in payload["cohorts"]} >= {"ClusterBuy", "OpenMarketSell"}


def test_scan_exposes_section16_without_applied_impact():
    base = build_unavailable_section16_insider_view("fixture")
    from dataclasses import replace

    analysis = type("A", (), {})()
    analysis.section16_insider_view = replace(
        base,
        status="constructive",
        score=72,
        coverage_score=100,
        modeled_impact=3,
        applied_impact=0,
        cluster_flag=True,
        freshness_source="edgar_form4_xml",
        stale_vs_sla=False,
        signed_value_usd=250000.0,
        streak_flag=False,
    )
    fields = _section16_insider_fields(analysis)
    assert fields["section16_applied_impact"] == 0
    assert fields["section16_cluster_flag"] is True


def test_rank_results_still_sorts_by_existing_scores(monkeypatch):
    analyses = [
        type("A", (), {"ticker": "BUY", "long_score": 82, "short_score": 77, "long_label": "Strong Buy", "short_label": "Strong Setup"})(),
        type("A", (), {"ticker": "HOLD", "long_score": 52, "short_score": 46, "long_label": "Hold", "short_label": "Neutral"})(),
    ]
    monkeypatch.setattr("application.scan_service._passes_universe_filters", lambda analysis: True)
    monkeypatch.setattr("application.scan_service._build_market_row", lambda analysis: {"ticker": analysis.ticker})
    monkeypatch.setattr(
        "application.scan_service._build_long_term_row",
        lambda analysis: {"ticker": analysis.ticker, "long_term_score": analysis.long_score, "recommendation_label": analysis.long_label},
    )
    monkeypatch.setattr(
        "application.scan_service._build_short_term_row",
        lambda analysis: {
            "ticker": analysis.ticker,
            "short_term_score": analysis.short_score,
            "recommendation_label": analysis.short_label,
            "ranking_bucket": "NO_SETUP",
        },
    )
    _, long_rows, short_rows = _rank_results(analyses)
    assert [row["recommendation_label"] for row in long_rows] == ["Strong Buy", "Hold"]
    assert [row["ticker"] for row in short_rows] == ["BUY", "HOLD"]
