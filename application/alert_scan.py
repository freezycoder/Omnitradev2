from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from config.settings import DATA_MODE_LIVE
from storage.repositories.email_dispatch_repository import EmailDispatchRepository


ScanFunction = Callable[..., dict[str, Any]]


def load_alert_payload(
    *,
    kind: str,
    ledger: EmailDispatchRepository,
    now: datetime,
    scan_fn: ScanFunction,
) -> dict[str, Any]:
    """Return a live scan, reusing an urgent payload that is younger than 20 minutes."""

    if kind == "urgent":
        cached = ledger.load_fresh_scan(now)
        if cached is not None:
            return cached
    payload = scan_fn(data_mode=DATA_MODE_LIVE, allow_demo_fallback=False)
    status = payload.get("data_status") if isinstance(payload.get("data_status"), dict) else {}
    if (
        payload.get("source") == "live"
        and status.get("status") == "fresh"
        and status.get("is_actionable") is True
    ):
        ledger.save_scan(payload, now)
    return payload
