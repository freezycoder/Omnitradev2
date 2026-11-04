from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from storage.repositories.email_dispatch_repository import (
    MemoryEmailDispatchRepository,
    new_record,
    reusable_scan,
)
from storage.repositories.postgres_email_dispatch import PostgresEmailDispatchRepository


def test_reusable_scan_expires_at_twenty_minutes() -> None:
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    payload = {"source": "live", "data_status": {"status": "fresh", "is_actionable": True}}

    assert reusable_scan(payload, now - timedelta(minutes=19), now) == payload
    assert reusable_scan(payload, now - timedelta(minutes=20), now) is None
    assert reusable_scan(payload, now + timedelta(seconds=1), now) is None
    assert reusable_scan({"source": "cached_real", "data_status": payload["data_status"]}, now, now) is None


def test_memory_find_weekly_returns_the_latest_row_for_that_iso_week() -> None:
    repo = MemoryEmailDispatchRepository()
    quiet = new_record(
        dedupe_key="weekly|2026-W44|default|alerts_v1",
        kind="weekly_quiet",
        ticker=None,
        strategy_family="long_term",
        signal_date="2026-W44",
        payload_hash="quiet",
        status="sent",
        created_at="2026-11-01T18:10:00+00:00",
        sent_at="2026-11-01T18:10:00+00:00",
    )
    other_week = new_record(
        dedupe_key="weekly|2026-W43|default|alerts_v1",
        kind="weekly_digest",
        ticker=None,
        strategy_family="long_term",
        signal_date="2026-W43",
        payload_hash="old",
        status="sent",
        created_at="2026-10-25T18:10:00+00:00",
        sent_at="2026-10-25T18:10:00+00:00",
    )
    repo.insert(quiet)
    repo.insert(other_week)

    found = repo.find_weekly("2026-W44")
    assert found is not None
    assert found.dedupe_key == quiet.dedupe_key
    assert repo.find_weekly("2026-W45") is None


def test_postgres_find_weekly_queries_digest_and_quiet_kinds() -> None:
    conn = FakeConnection(
        row={
            "dedupe_key": "weekly|2026-W44|default|alerts_v1",
            "kind": "weekly_digest",
            "ticker": None,
            "strategy_family": "long_term",
            "signal_date": "2026-W44",
            "payload_hash": "abc",
            "status": "sent",
            "provider_message_id": "msg_44",
            "attempt_count": 1,
            "last_error": None,
            "created_at": "2026-11-01T18:10:00+00:00",
            "sent_at": "2026-11-01T18:10:00+00:00",
        }
    )
    repo = PostgresEmailDispatchRepository("postgresql://db.example/omnitrade", connect=lambda: conn)

    found = repo.find_weekly("2026-W44")

    assert found is not None
    assert found.signal_date == "2026-W44"
    assert found.status == "sent"
    sql, params = conn.calls[0]
    assert "kind IN ('weekly_digest', 'weekly_quiet')" in sql
    assert params == ("2026-W44",)


def test_postgres_insert_turns_a_unique_violation_into_key_error() -> None:
    conn = FakeConnection(error=psycopg.errors.UniqueViolation("duplicate key"))
    repo = PostgresEmailDispatchRepository("postgresql://db.example/omnitrade", connect=lambda: conn)
    record = new_record(
        dedupe_key="weekly|2026-W42|default|alerts_v1",
        kind="weekly_quiet",
        ticker=None,
        strategy_family="long_term",
        signal_date="2026-W42",
        payload_hash="abc",
        status="pending",
        created_at="2026-10-18T17:30:00+00:00",
        attempt_count=1,
    )

    with pytest.raises(KeyError, match="weekly\\|2026-W42"):
        repo.insert(record)


def test_postgres_save_persists_a_sent_receipt() -> None:
    conn = FakeConnection()
    repo = PostgresEmailDispatchRepository("postgresql://db.example/omnitrade", connect=lambda: conn)
    record = new_record(
        dedupe_key="urgent|NVDA|short_term_day|ENTER NOW|2026-10-14|alerts_v1",
        kind="urgent",
        ticker="NVDA",
        strategy_family="short_term_day",
        signal_date="2026-10-14",
        payload_hash="abc",
        status="sent",
        created_at="2026-10-14T14:00:00+00:00",
        attempt_count=1,
        provider_message_id="msg_123",
        sent_at="2026-10-14T14:00:01+00:00",
    )

    repo.save(record)

    sql, params = conn.calls[0]
    assert "UPDATE email_dispatches" in sql
    assert params["status"] == "sent"
    assert params["provider_message_id"] == "msg_123"
    assert params["dedupe_key"] == record.dedupe_key


def test_postgres_load_fresh_scan_uses_the_reuse_window() -> None:
    now = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    payload = {"source": "live", "data_status": {"status": "fresh", "is_actionable": True}, "ticker": "NVDA"}
    fresh = FakeConnection(
        row={
            "scanned_at": (now - timedelta(minutes=10)).isoformat(),
            "payload_json": json.dumps(payload),
        }
    )
    stale = FakeConnection(
        row={
            "scanned_at": (now - timedelta(minutes=21)).isoformat(),
            "payload_json": json.dumps(payload),
        }
    )

    fresh_repo = PostgresEmailDispatchRepository("postgresql://db.example/omnitrade", connect=lambda: fresh)
    stale_repo = PostgresEmailDispatchRepository("postgresql://db.example/omnitrade", connect=lambda: stale)

    assert fresh_repo.load_fresh_scan(now)["ticker"] == "NVDA"
    assert stale_repo.load_fresh_scan(now) is None
    assert "alert_scan_markers" in fresh.calls[0][0]


class FakeConnection:
    def __init__(self, row: dict | None = None, error: Exception | None = None) -> None:
        self.row = row
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))
        if self.error is not None:
            raise self.error
        return self

    def fetchone(self):
        return self.row
