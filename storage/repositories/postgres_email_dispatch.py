from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from domain.alerts.models import DispatchRecord, DispatchStatus
from storage.repositories.email_dispatch_repository import new_record, reusable_scan


_DISPATCH_DDL = """
CREATE TABLE IF NOT EXISTS email_dispatches (
    dedupe_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    ticker TEXT,
    strategy_family TEXT,
    signal_date TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    provider_message_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
)
"""

_SCAN_DDL = """
CREATE TABLE IF NOT EXISTS alert_scan_markers (
    marker_key TEXT PRIMARY KEY,
    scanned_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
)
"""


class PostgresEmailDispatchRepository:
    """Durable dispatch ledger. The free Render disk is not this store."""

    def __init__(self, database_url: str, *, connect: Callable[[], Any] | None = None) -> None:
        if not database_url.strip():
            raise ValueError("OMNITRADE_ALERT_DATABASE_URL is required")
        self.database_url = database_url
        self._connect_override = connect
        if connect is None:
            self._ensure_schema()

    def get(self, dedupe_key: str) -> DispatchRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM email_dispatches WHERE dedupe_key = %s",
                (dedupe_key,),
            ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def find_weekly(self, iso_week: str) -> DispatchRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM email_dispatches
                WHERE signal_date = %s AND kind IN ('weekly_digest', 'weekly_quiet')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (iso_week,),
            ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def insert(self, record: DispatchRecord) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO email_dispatches (
                        dedupe_key, kind, ticker, strategy_family, signal_date,
                        payload_hash, status, provider_message_id, attempt_count,
                        last_error, created_at, sent_at
                    ) VALUES (
                        %(dedupe_key)s, %(kind)s, %(ticker)s, %(strategy_family)s, %(signal_date)s,
                        %(payload_hash)s, %(status)s, %(provider_message_id)s, %(attempt_count)s,
                        %(last_error)s, %(created_at)s, %(sent_at)s
                    )
                    """,
                    _record_params(record),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise KeyError(record.dedupe_key) from exc

    def save(self, record: DispatchRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE email_dispatches SET
                    kind = %(kind)s,
                    ticker = %(ticker)s,
                    strategy_family = %(strategy_family)s,
                    signal_date = %(signal_date)s,
                    payload_hash = %(payload_hash)s,
                    status = %(status)s,
                    provider_message_id = %(provider_message_id)s,
                    attempt_count = %(attempt_count)s,
                    last_error = %(last_error)s,
                    created_at = %(created_at)s,
                    sent_at = %(sent_at)s
                WHERE dedupe_key = %(dedupe_key)s
                """,
                _record_params(record),
            )

    def save_scan(self, payload: dict[str, Any], scanned_at: datetime) -> None:
        scanned = scanned_at.astimezone(timezone.utc).isoformat()
        encoded = json.dumps(payload, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_scan_markers (marker_key, scanned_at, payload_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (marker_key) DO UPDATE
                SET scanned_at = EXCLUDED.scanned_at,
                    payload_json = EXCLUDED.payload_json
                """,
                ("latest_live", scanned, encoded),
            )

    def load_fresh_scan(self, now: datetime) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT scanned_at, payload_json FROM alert_scan_markers WHERE marker_key = %s",
                ("latest_live",),
            ).fetchone()
        if row is None:
            return None
        scanned_at = datetime.fromisoformat(row["scanned_at"])
        payload = json.loads(row["payload_json"])
        if not isinstance(payload, dict):
            return None
        return reusable_scan(payload, scanned_at, now)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(_DISPATCH_DDL)
            conn.execute(_SCAN_DDL)

    def _connect(self) -> Any:
        if self._connect_override is not None:
            return self._connect_override()
        return psycopg.connect(self.database_url, row_factory=dict_row)


def _record_params(record: DispatchRecord) -> dict[str, Any]:
    return {
        "dedupe_key": record.dedupe_key,
        "kind": record.kind,
        "ticker": record.ticker,
        "strategy_family": record.strategy_family,
        "signal_date": record.signal_date,
        "payload_hash": record.payload_hash,
        "status": record.status,
        "provider_message_id": record.provider_message_id,
        "attempt_count": record.attempt_count,
        "last_error": record.last_error,
        "created_at": record.created_at,
        "sent_at": record.sent_at,
    }


def _record_from_row(row: dict[str, Any]) -> DispatchRecord:
    status: DispatchStatus = row["status"]
    return new_record(
        dedupe_key=row["dedupe_key"],
        kind=row["kind"],
        ticker=row["ticker"],
        strategy_family=row["strategy_family"],
        signal_date=row["signal_date"],
        payload_hash=row["payload_hash"],
        status=status,
        created_at=row["created_at"],
        attempt_count=int(row["attempt_count"]),
        provider_message_id=row["provider_message_id"],
        last_error=row["last_error"],
        sent_at=row["sent_at"],
    )
