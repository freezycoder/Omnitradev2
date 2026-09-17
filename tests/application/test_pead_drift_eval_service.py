from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from application.pead_drift_eval_service import PeadDriftEvalService
from domain.evaluation.pead_experiment import (
    PRIMARY_SURPRISE_ABS_PCT,
    PeadEventObservation,
    PeadHorizonObservation,
    decide_verdict,
)


def _event(
    index: int,
    *,
    surprise: float = 8.0,
    drift: float = 2.0,
    ticker_offset: int = 0,
) -> PeadEventObservation:
    event_date = date(2024, 1, 2) + timedelta(weeks=index)
    aligned = drift
    sign = "beat" if surprise > 0 else "miss"
    spy_excess_3 = 0.20 if surprise > 0 else -0.20
    spy_excess_later = aligned if surprise > 0 else -aligned
    return PeadEventObservation(
        ticker=f"T{(index + ticker_offset) % 17}",
        event_date=event_date,
        period=event_date.isoformat(),
        surprise_pct=surprise,
        surprise_sign=sign,
        event_date_source="sec_filing",
        sector="Technology" if index % 2 == 0 else "Healthcare",
        size_bucket="large" if index % 3 else "mid",
        market_cap=40_000_000_000,
        horizons=(
            PeadHorizonObservation(3, True, 0.4, spy_excess_3, spy_excess_3),
            PeadHorizonObservation(10, True, 1.0, spy_excess_later / 2, spy_excess_later / 2),
            PeadHorizonObservation(20, True, 2.0, spy_excess_later, spy_excess_later),
            PeadHorizonObservation(60, True, 3.0, spy_excess_later, spy_excess_later),
        ),
    )


def test_pead_eval_aborts_as_data_blocked_when_n_unmet():
    payload = PeadDriftEvalService(events=[_event(0), _event(1, surprise=-7.0)]).build_payload()

    assert payload["mode"] == "shadow"
    assert payload["automatic_activation"] is False
    assert payload["cannot_flip_live"] is True
    assert payload["live_score_changes"] is False
    assert payload["lifecycle_label"] == "UNVERIFIED"
    assert payload["lifecycle_stage"] == "in_sample"
    assert payload["promotion"]["live_write_allowed"] is False
    assert payload["promotion"]["qualified_plus"] is False
    assert "multiple_testing" in payload["promotion"]["missing_gates"]
    assert "forward_paper" in payload["promotion"]["missing_gates"]
    assert payload["verdict"] == "data_blocked"
    assert payload["protocol"]["primary_surprise_abs_pct"] == PRIMARY_SURPRISE_ABS_PCT
    assert "data-blocked" in payload["summary"]


def test_pead_eval_succeeds_on_pre_registered_large_surprise_drift():
    events = [_event(index, drift=2.4) for index in range(80)]
    payload = PeadDriftEvalService(events=events).build_payload()

    assert payload["verdict"] == "success"
    assert payload["live_score_changes"] is False
    assert payload["automatic_activation"] is False
    assert payload["cannot_flip_live"] is True
    assert payload["lifecycle_label"] == "UNVERIFIED"
    assert payload["lifecycle_stage"] == "in_sample"
    assert payload["promotion"]["live_write_allowed"] is False
    assert payload["promotion"]["qualified_plus"] is False
    passed = payload["diagnostic"]["confirmatory_passed"]
    assert 20 in passed or 60 in passed
    twenty = next(row for row in payload["confirmatory_horizons"] if row["sessions"] == 20)
    assert twenty["testable"] is True
    assert twenty["passed"] is True
    assert twenty["oos"]["mean_after_cost_pct"] > 0
    assert twenty["incremental_vs_3_session"]["mean_gross_increment_pct"] >= 0.5


def test_pead_eval_fails_when_there_is_no_incremental_drift():
    events = [_event(index, drift=0.2) for index in range(80)]
    # Force later horizons to equal the 3-session move.
    flattened: list[PeadEventObservation] = []
    for event in events:
        row = event.horizon(3)
        assert row is not None
        spy = row.market_excess_pct
        assert spy is not None
        flattened.append(
            PeadEventObservation(
                ticker=event.ticker,
                event_date=event.event_date,
                period=event.period,
                surprise_pct=event.surprise_pct,
                surprise_sign=event.surprise_sign,
                event_date_source=event.event_date_source,
                sector=event.sector,
                size_bucket=event.size_bucket,
                market_cap=event.market_cap,
                horizons=(
                    PeadHorizonObservation(3, True, 0.2, spy, spy),
                    PeadHorizonObservation(10, True, 0.2, spy, spy),
                    PeadHorizonObservation(20, True, 0.2, spy, spy),
                    PeadHorizonObservation(60, True, 0.2, spy, spy),
                ),
            )
        )
    payload = PeadDriftEvalService(events=flattened).build_payload()

    assert payload["verdict"] == "fail"
    assert payload["automatic_activation"] is False


def test_secondary_strata_do_not_change_verdict():
    events = [_event(index, drift=0.2) for index in range(80)]
    payload = PeadDriftEvalService(events=events).build_payload()

    assert payload["verdict"] == "fail"
    assert payload["secondary_size"]
    assert payload["secondary_sector"]
    assert all(row["role"] == "descriptive_only" for row in payload["secondary_size"])
    assert all(row["role"] == "descriptive_only" for row in payload["surprise_buckets"] if row["abs_cut_pct"] != 5.0)


def test_decide_verdict_is_data_blocked_when_no_horizon_is_testable():
    assert decide_verdict([{"sessions": 20, "passed": False, "testable": False}]) == "data_blocked"
    assert decide_verdict([{"sessions": 20, "passed": False, "testable": True}]) == "fail"
    assert decide_verdict([{"sessions": 60, "passed": True, "testable": True}]) == "success"


class _SqliteOutcomeRepository:
    def __init__(self, rows):
        self._rows = rows

    def ensure_schema(self):
        return None

    def list_calibration_observations(self):
        return self._rows


def test_pead_eval_reads_sqlite_row_objects_without_get():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        "create table observations (ticker text, created_at text, feature_snapshot_json text)"
    )
    snapshot = {
        "ticker": "AAPL",
        "earnings_intelligence": {
            "event_drift": [
                {
                    "event_date": "2024-01-15",
                    "period": "2023-12-31",
                    "surprise_pct": 8.0,
                    "event_date_source": "sec_filing",
                    "sector": "Technology",
                    "size_bucket": "large",
                    "market_cap": 2_000_000_000_000,
                    "horizons": [
                        {
                            "sessions": 3,
                            "complete": True,
                            "stock_return_pct": 1.0,
                            "market_excess_pct": 0.5,
                            "sector_excess_pct": 0.4,
                        },
                        {
                            "sessions": 10,
                            "complete": True,
                            "stock_return_pct": 2.0,
                            "market_excess_pct": 1.0,
                            "sector_excess_pct": 0.8,
                        },
                        {
                            "sessions": 20,
                            "complete": True,
                            "stock_return_pct": 3.0,
                            "market_excess_pct": 1.5,
                            "sector_excess_pct": 1.2,
                        },
                        {
                            "sessions": 60,
                            "complete": True,
                            "stock_return_pct": 4.0,
                            "market_excess_pct": 2.0,
                            "sector_excess_pct": 1.6,
                        },
                    ],
                }
            ]
        },
    }
    connection.execute(
        "insert into observations values (?, ?, ?)",
        ("AAPL", "2024-02-01T00:00:00", json.dumps(snapshot)),
    )
    row = connection.execute("select * from observations").fetchone()
    assert not hasattr(row, "get")

    payload = PeadDriftEvalService(
        outcome_repository=_SqliteOutcomeRepository([row])
    ).build_payload()

    assert payload["verdict"] == "data_blocked"
    assert payload["cannot_flip_live"] is True
    assert payload["live_score_changes"] is False
    assert payload["primary_event_count"] == 1
    assert payload["automatic_activation"] is False
