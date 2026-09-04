from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from config.settings import CACHE_FRESHNESS_HOURS, SOURCE_CONFIG
from domain.signals.signal_buckets import apply_short_term_signal_buckets
from domain.signals.trade_levels import apply_scan_trade_level_policy


_ACTIONABLE_TRADE_STATES = {
    "ENTER NOW",
    "CONFIRMED BREAKOUT — BUY",
    "CONFIRMED BREAKDOWN — SELL",
}
_PRICE_LEVEL_FIELDS = (
    "entry_price",
    "target_price",
    "stop_loss_price",
    "breakout_level",
    "breakdown_level",
    "entry",
    "target",
    "stop_loss",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_actionable_row(row: dict[str, Any]) -> bool:
    state = str(row.get("trade_state") or "").strip().upper()
    return bool(row.get("is_actionable_now")) or state in _ACTIONABLE_TRADE_STATES


def _blocked_state(source_status: str) -> str:
    if source_status == "demo":
        return "DEMO — NOT ACTIONABLE"
    if source_status == "unavailable":
        return "DATA UNAVAILABLE"
    return "STALE — REFRESH REQUIRED"


def _sanitize_trade_horizon(
    value: Any,
    *,
    block_reason: str,
    source_status: str,
) -> Any:
    if not isinstance(value, dict):
        return value
    horizon = dict(value)
    original_state = str(horizon.get("trade_state") or "").strip()
    if original_state and original_state.upper() in _ACTIONABLE_TRADE_STATES:
        horizon["trade_state"] = _blocked_state(source_status)
        horizon["trade_state_tone"] = "negative"
        horizon["explanation"] = block_reason
    horizon.pop("original_trade_state", None)
    horizon["is_actionable_now"] = False
    horizon["action_block_reason"] = block_reason
    for field in _PRICE_LEVEL_FIELDS:
        if field in horizon:
            horizon[field] = None
    return horizon


def _sanitize_short_row(
    row: dict[str, Any],
    *,
    block_reason: str,
    source_status: str,
) -> dict[str, Any]:
    sanitized = dict(row)
    was_actionable = _is_actionable_row(sanitized)
    if was_actionable:
        sanitized["trade_state"] = _blocked_state(source_status)
        sanitized["trade_state_tone"] = "negative"
        sanitized["trade_state_explanation"] = block_reason
    sanitized.pop("original_trade_state", None)
    sanitized.pop("original_recommendation_label", None)
    sanitized["is_actionable_now"] = False
    sanitized["action_block_reason"] = block_reason
    for field in _PRICE_LEVEL_FIELDS:
        if field in sanitized:
            sanitized[field] = None
    sanitized["day_trade"] = _sanitize_trade_horizon(
        sanitized.get("day_trade"),
        block_reason=block_reason,
        source_status=source_status,
    )
    sanitized["swing_trade"] = _sanitize_trade_horizon(
        sanitized.get("swing_trade"),
        block_reason=block_reason,
        source_status=source_status,
    )
    return sanitized


def _sanitize_market_row(
    row: dict[str, Any],
    *,
    block_reason: str,
    source_status: str,
) -> dict[str, Any]:
    sanitized = dict(row)
    state = str(sanitized.get("trade_state") or "").strip()
    if state.upper() in _ACTIONABLE_TRADE_STATES:
        sanitized["trade_state"] = _blocked_state(source_status)
        sanitized["action_block_reason"] = block_reason
    sanitized.pop("original_trade_state", None)
    return sanitized


def apply_scan_freshness_policy(
    payload: dict[str, Any],
    *,
    source_override: str | None = None,
    now: datetime | None = None,
    max_age_hours: float = CACHE_FRESHNESS_HOURS,
) -> dict[str, Any]:
    """Return a scan payload with stale or synthetic execution signals disabled.

    Rankings and explanatory research remain available, but actionable trade
    states and price levels are removed unless real data has a valid timestamp
    inside the configured freshness window.
    """

    protected = apply_scan_trade_level_policy(deepcopy(payload))
    delivered_at = now or datetime.now(UTC)
    delivered_at = delivered_at.astimezone(UTC) if delivered_at.tzinfo else delivered_at.replace(tzinfo=UTC)
    source = str(source_override or protected.get("source") or "unavailable").strip().lower()
    captured_at = _parse_timestamp(protected.get("updated_at"))

    age_seconds: float | None = None
    timestamp_valid = captured_at is not None
    if captured_at is not None:
        age_seconds = (delivered_at - captured_at).total_seconds()
        # Allow a small amount of clock skew, but fail closed on future-dated scans.
        if age_seconds < -300:
            timestamp_valid = False
        elif age_seconds < 0:
            age_seconds = 0.0

    max_age_seconds = max(float(max_age_hours), 0.0) * 3600
    source_meta = SOURCE_CONFIG.get(source)
    source_allows_actions = bool(source_meta and source_meta.allow_actionable_recommendations)
    temporally_fresh = bool(
        timestamp_valid
        and age_seconds is not None
        and age_seconds <= max_age_seconds
    )
    is_actionable = source_allows_actions and temporally_fresh

    if source == "demo":
        status = "demo"
        block_reason = "Demo data is for testing only. Actionable signals and price levels are disabled."
    elif source == "unavailable":
        status = "unavailable"
        block_reason = "Market data is unavailable. Actionable signals and price levels are disabled."
    elif not timestamp_valid:
        status = "stale"
        block_reason = "The scan timestamp is missing, invalid, or in the future. Refresh before using any signal."
    elif not temporally_fresh:
        status = "stale"
        block_reason = (
            f"Scan data is older than {max_age_hours:g} hours. "
            "Actionable signals and price levels are disabled until a fresh scan completes."
        )
    elif not source_allows_actions:
        status = "unavailable"
        block_reason = "This data source is not approved for actionable signals."
    else:
        status = "fresh"
        block_reason = None

    short_rows = [dict(row) for row in protected.get("short_term", []) if isinstance(row, dict)]
    detected_actionable_count = sum(1 for row in short_rows if _is_actionable_row(row))
    previous_status = protected.get("data_status") if isinstance(protected.get("data_status"), dict) else {}
    previous_blocked_count = previous_status.get("blocked_actionable_count")
    blocked_actionable_count = max(
        detected_actionable_count,
        int(previous_blocked_count) if isinstance(previous_blocked_count, (int, float)) else 0,
    )

    if not is_actionable:
        short_rows = [
            _sanitize_short_row(row, block_reason=block_reason or "Actionable signals are disabled.", source_status=status)
            for row in short_rows
        ]
        protected["long_term"] = [
            {
                **row,
                "tone": "warning",
                "is_actionable": False,
                "action_block_reason": block_reason,
            }
            for row in protected.get("long_term", [])
            if isinstance(row, dict)
        ]
        protected["market_rows"] = [
            _sanitize_market_row(
                row,
                block_reason=block_reason or "Actionable signals are disabled.",
                source_status=status,
            )
            for row in protected.get("market_rows", [])
            if isinstance(row, dict)
        ]

    protected["short_term"] = short_rows
    protected["source"] = source
    for collection in ("market_rows", "long_term", "short_term"):
        protected[collection] = [
            {**row, "data_source": source}
            for row in protected.get(collection, [])
            if isinstance(row, dict)
        ]

    market_stats = dict(protected.get("market_stats") or {})
    market_stats["actionable_now"] = sum(1 for row in short_rows if row.get("is_actionable_now")) if is_actionable else 0
    market_stats["blocked_actionable_count"] = blocked_actionable_count if not is_actionable else 0
    protected["market_stats"] = market_stats
    protected["data_status"] = {
        "source": source,
        "captured_at": captured_at.isoformat() if captured_at else None,
        "delivered_at": delivered_at.isoformat(),
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "age_hours": round(age_seconds / 3600, 2) if age_seconds is not None else None,
        "max_age_hours": max_age_hours,
        "status": status,
        "is_stale": status == "stale",
        "is_actionable": is_actionable,
        "blocked_actionable_count": blocked_actionable_count if not is_actionable else 0,
        "block_reason": block_reason,
    }
    return apply_short_term_signal_buckets(protected)


__all__ = ["apply_scan_freshness_policy"]
