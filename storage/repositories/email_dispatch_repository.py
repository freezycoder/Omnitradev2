from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from domain.alerts.models import WEEKLY_DISPATCH_KINDS, DispatchRecord, DispatchStatus


SCAN_REUSE_SECONDS = 20 * 60
SCAN_MARKER_KEY = "latest_live"


class EmailDispatchRepository(Protocol):
    def get(self, dedupe_key: str) -> DispatchRecord | None: ...

    def find_weekly(self, iso_week: str) -> DispatchRecord | None: ...

    def insert(self, record: DispatchRecord) -> None: ...

    def save(self, record: DispatchRecord) -> None: ...

    def save_scan(self, payload: dict[str, Any], scanned_at: datetime) -> None: ...

    def load_fresh_scan(self, now: datetime) -> dict[str, Any] | None: ...


class MemoryEmailDispatchRepository:
    """In-memory ledger used by tests and by a local dry run."""

    def __init__(self) -> None:
        self.rows: dict[str, DispatchRecord] = {}
        self._scan_payload: dict[str, Any] | None = None
        self._scan_at: datetime | None = None

    def get(self, dedupe_key: str) -> DispatchRecord | None:
        return self.rows.get(dedupe_key)

    def find_weekly(self, iso_week: str) -> DispatchRecord | None:
        matches = [
            record
            for record in self.rows.values()
            if record.signal_date == iso_week and record.kind in WEEKLY_DISPATCH_KINDS
        ]
        if not matches:
            return None
        return max(matches, key=lambda record: record.created_at)

    def insert(self, record: DispatchRecord) -> None:
        if record.dedupe_key in self.rows:
            raise KeyError(record.dedupe_key)
        self.rows[record.dedupe_key] = record

    def save(self, record: DispatchRecord) -> None:
        self.rows[record.dedupe_key] = record

    def save_scan(self, payload: dict[str, Any], scanned_at: datetime) -> None:
        self._scan_payload = dict(payload)
        self._scan_at = scanned_at.astimezone(timezone.utc)

    def load_fresh_scan(self, now: datetime) -> dict[str, Any] | None:
        return reusable_scan(self._scan_payload, self._scan_at, now)


def reusable_scan(
    payload: dict[str, Any] | None,
    scanned_at: datetime | None,
    now: datetime,
) -> dict[str, Any] | None:
    """Return a stored live scan only while it is still inside the reuse window."""

    if payload is None or scanned_at is None:
        return None
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - scanned_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < 0 or age_seconds >= SCAN_REUSE_SECONDS:
        return None
    status = payload.get("data_status")
    if payload.get("source") != "live" or not isinstance(status, dict):
        return None
    if status.get("status") != "fresh" or status.get("is_actionable") is not True:
        return None
    return dict(payload)


def new_record(
    *,
    dedupe_key: str,
    kind: str,
    ticker: str | None,
    strategy_family: str | None,
    signal_date: str,
    payload_hash: str,
    status: DispatchStatus,
    created_at: str,
    attempt_count: int = 0,
    provider_message_id: str | None = None,
    last_error: str | None = None,
    sent_at: str | None = None,
) -> DispatchRecord:
    return DispatchRecord(
        dedupe_key=dedupe_key,
        kind=kind,
        ticker=ticker,
        strategy_family=strategy_family,
        signal_date=signal_date,
        payload_hash=payload_hash,
        status=status,
        provider_message_id=provider_message_id,
        attempt_count=attempt_count,
        last_error=last_error,
        created_at=created_at,
        sent_at=sent_at,
    )
