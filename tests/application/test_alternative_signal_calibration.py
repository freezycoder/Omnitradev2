from __future__ import annotations

import json
from datetime import date, timedelta

from application.calibration_service import CalibrationService


class _OutcomeRepository:
    def __init__(self, rows):
        self._rows = rows

    def list_calibration_observations(self):
        return self._rows

    @staticmethod
    def _rows_to_expectancy_stats(rows):
        from storage.repositories.outcome_repository import OutcomeRepository

        return OutcomeRepository._rows_to_expectancy_stats(rows)


def _row(index: int, impact: int, realized_return: float):
    created = date(2026, 1, 1) + timedelta(days=index)
    return {
        "signal_id": f"signal-{index}",
        "ticker": f"T{index % 10}",
        "created_at": created.isoformat(),
        "realized_return_pct": realized_return,
        "feature_snapshot_json": json.dumps(
            {
                "alternative_signal": {
                    "score": 50 + impact * 5,
                    "modeled_impact": impact,
                    "coverage_score": 90,
                }
            }
        ),
    }


def _relative_row(index: int, score: int, realized_return: float):
    row = _row(index, 0, realized_return)
    row["feature_snapshot_json"] = json.dumps(
        {
            "relative_strength": {
                "score": score,
                "coverage_score": 100,
            }
        }
    )
    return row


def _earnings_row(index: int, score: int, realized_return: float):
    row = _row(index, 0, realized_return)
    row["feature_snapshot_json"] = json.dumps(
        {
            "earnings_intelligence": {
                "score": score,
                "coverage_score": 90,
                "event_risk": "normal",
            }
        }
    )
    return row


def test_alternative_signal_calibration_stays_locked_below_evidence_gate():
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository(
        [_row(index, 2 if index % 2 == 0 else -2, 1.0 if index % 2 == 0 else -1.0) for index in range(20)]
    )

    payload = service.get_alternative_signal_analysis()

    assert payload["mode"] == "shadow"
    assert payload["activation_ready"] is False
    assert payload["requirements"]["minimum_resolved_signals"]["passed"] is False
    assert payload["directional_net_expectancy_pct"] > 0


def test_alternative_signal_calibration_separates_unknown_legacy_rows():
    legacy_row = _row(1, 1, 0.5)
    legacy_row["feature_snapshot_json"] = "{}"
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository([legacy_row])

    payload = service.get_alternative_signal_analysis()

    assert payload["directional_resolved_signals"] == 0
    assert payload["cohorts"][0]["shadow_band"] == "Unknown"


def test_relative_strength_calibration_rewards_aligned_leaders_and_laggards():
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository(
        [
            _relative_row(
                index,
                75 if index % 2 == 0 else 25,
                1.0 if index % 2 == 0 else -1.0,
            )
            for index in range(60)
        ]
    )

    payload = service.get_relative_strength_analysis()

    assert payload["directional_resolved_signals"] == 60
    assert payload["directional_net_expectancy_pct"] > 0
    assert payload["requirements"]["minimum_resolved_signals"]["passed"] is True
    assert {row["relative_strength_band"] for row in payload["cohorts"]} == {"Leader", "Laggard"}


def test_earnings_intelligence_calibration_rewards_aligned_score_bands():
    service = CalibrationService.__new__(CalibrationService)
    service._outcome_repository = _OutcomeRepository(
        [
            _earnings_row(
                index,
                75 if index % 2 == 0 else 25,
                1.0 if index % 2 == 0 else -1.0,
            )
            for index in range(60)
        ]
    )

    payload = service.get_earnings_intelligence_analysis()

    assert payload["directional_resolved_signals"] == 60
    assert payload["directional_net_expectancy_pct"] > 0
    assert payload["requirements"]["minimum_resolved_signals"]["passed"] is True
    assert {
        row["earnings_intelligence_band"]
        for row in payload["cohorts"]
    } == {"Strong", "Deteriorating"}
