from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


ALERT_MODEL_VERSION = "alerts_v1"
NY_ZONE = ZoneInfo("America/New_York")


def ny_session_date(now: datetime) -> str:
    return now.astimezone(NY_ZONE).date().isoformat()


def iso_week_label(now: datetime, timezone_name: str) -> str:
    local = now.astimezone(ZoneInfo(timezone_name))
    year, week, _day = local.isocalendar()
    return f"{year}-W{week:02d}"


def urgent_dedupe_key(
    *,
    ticker: str,
    family: str,
    session_date: str,
    model_version: str = ALERT_MODEL_VERSION,
) -> str:
    return f"urgent|{ticker.upper()}|{family}|ENTER NOW|{session_date}|{model_version}"


def weekly_dedupe_key(
    *,
    iso_week: str,
    universe_name: str,
    model_version: str = ALERT_MODEL_VERSION,
) -> str:
    """One key per ISO week, whether the mail is a digest or a quiet note."""

    return f"weekly|{iso_week}|{universe_name}|{model_version}"


def payload_fingerprint(kind: str, rows: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> str:
    material = []
    for row in rows:
        material.append(
            {
                "ticker": row.get("ticker"),
                "long_term_score": row.get("long_term_score"),
                "short_term_score": row.get("short_term_score"),
                "label": row.get("recommendation_label"),
            }
        )
    encoded = json.dumps({"kind": kind, "rows": material}, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
