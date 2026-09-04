from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal


ShortTermSignalBucket = Literal["active", "waiting", "excluded"]

ACTIVE_BUCKET: ShortTermSignalBucket = "active"
WAITING_BUCKET: ShortTermSignalBucket = "waiting"
EXCLUDED_BUCKET: ShortTermSignalBucket = "excluded"

_ACTIONABLE_TRADE_STATES = {
    "ENTER NOW",
    "CONFIRMED BREAKOUT — BUY",
    "CONFIRMED BREAKDOWN — SELL",
}
_WAITING_TRADE_STATES = {
    "WAIT FOR PULLBACK",
    "BREAKOUT WATCH",
    "BREAKDOWN WATCH",
}
_WAITING_RECOMMENDATIONS = {
    "STRONG SETUP",
    "WATCHLIST",
}


def _normalized(value: Any) -> str:
    return str(value or "").strip().upper()


def classify_short_term_signal(row: dict[str, Any]) -> ShortTermSignalBucket:
    """Classify a short-term row by its current execution eligibility."""

    trade_state = _normalized(row.get("trade_state"))
    recommendation = _normalized(row.get("recommendation_label"))
    is_blocked = bool(str(row.get("action_block_reason") or "").strip())

    if (
        not is_blocked
        and row.get("is_actionable_now") is True
        and trade_state in _ACTIONABLE_TRADE_STATES
    ):
        return ACTIVE_BUCKET

    if is_blocked:
        return EXCLUDED_BUCKET

    if trade_state in _WAITING_TRADE_STATES or recommendation in _WAITING_RECOMMENDATIONS:
        return WAITING_BUCKET

    return EXCLUDED_BUCKET


def apply_short_term_signal_buckets(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach a bucket to every short-term row and publish exact bucket counts."""

    protected = deepcopy(payload)
    counts = {
        ACTIVE_BUCKET: 0,
        WAITING_BUCKET: 0,
        EXCLUDED_BUCKET: 0,
    }
    rows: list[dict[str, Any]] = []

    for source_row in protected.get("short_term", []):
        if not isinstance(source_row, dict):
            continue
        row = dict(source_row)
        bucket = classify_short_term_signal(row)
        row["signal_bucket"] = bucket
        counts[bucket] += 1
        rows.append(row)

    stats = dict(protected.get("market_stats") or {})
    stats["actionable_now"] = counts[ACTIVE_BUCKET]
    stats["short_term_buckets"] = counts
    protected["market_stats"] = stats
    protected["short_term"] = rows
    return protected


__all__ = [
    "ACTIVE_BUCKET",
    "EXCLUDED_BUCKET",
    "ShortTermSignalBucket",
    "WAITING_BUCKET",
    "apply_short_term_signal_buckets",
    "classify_short_term_signal",
]
