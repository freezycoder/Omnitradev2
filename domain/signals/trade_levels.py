from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any


MAX_STOP_DISTANCE_PCT = 35.0
MAX_TARGET_DISTANCE_PCT = 75.0
MAX_ENTRY_DEVIATION_PCT = 25.0
INVALID_TRADE_LEVEL_STATE = "INVALID LEVELS — REVIEW REQUIRED"

_ACTIONABLE_TRADE_STATES = {
    "ENTER NOW",
    "CONFIRMED BREAKOUT — BUY",
    "CONFIRMED BREAKDOWN — SELL",
}
_BRACKET_FIELDS = ("entry_price", "target_price", "stop_loss_price")
_DISPLAY_LEVEL_FIELDS = ("entry", "target", "stop_loss")


@dataclass(frozen=True)
class TradeLevelValidation:
    valid: bool
    reason: str | None
    risk_pct: float | None = None
    reward_pct: float | None = None
    entry_deviation_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def validate_long_trade_levels(
    *,
    entry_price: Any,
    target_price: Any,
    stop_loss_price: Any,
    reference_price: Any = None,
    max_stop_distance_pct: float = MAX_STOP_DISTANCE_PCT,
    max_target_distance_pct: float = MAX_TARGET_DISTANCE_PCT,
    max_entry_deviation_pct: float = MAX_ENTRY_DEVIATION_PCT,
) -> TradeLevelValidation:
    """Validate a long trade bracket before it can be treated as actionable."""

    entry = _finite_float(entry_price)
    target = _finite_float(target_price)
    stop = _finite_float(stop_loss_price)
    if entry is None or target is None or stop is None:
        return TradeLevelValidation(
            valid=False,
            reason="Entry, target, and stop must all be finite numeric prices.",
        )
    if not 0 < stop < entry < target:
        return TradeLevelValidation(
            valid=False,
            reason="Trade levels must satisfy 0 < stop < entry < target.",
        )

    risk_pct = ((entry - stop) / entry) * 100.0
    reward_pct = ((target - entry) / entry) * 100.0
    if risk_pct > max(float(max_stop_distance_pct), 0.0):
        return TradeLevelValidation(
            valid=False,
            reason=f"Stop distance exceeds the {max_stop_distance_pct:g}% safety limit.",
            risk_pct=round(risk_pct, 4),
            reward_pct=round(reward_pct, 4),
        )
    if reward_pct > max(float(max_target_distance_pct), 0.0):
        return TradeLevelValidation(
            valid=False,
            reason=f"Target distance exceeds the {max_target_distance_pct:g}% plausibility limit.",
            risk_pct=round(risk_pct, 4),
            reward_pct=round(reward_pct, 4),
        )

    reference = _finite_float(reference_price)
    entry_deviation_pct = None
    if reference is not None and reference > 0:
        entry_deviation_pct = (abs(entry - reference) / reference) * 100.0
        if entry_deviation_pct > max(float(max_entry_deviation_pct), 0.0):
            return TradeLevelValidation(
                valid=False,
                reason=f"Entry price is more than {max_entry_deviation_pct:g}% from the reference price.",
                risk_pct=round(risk_pct, 4),
                reward_pct=round(reward_pct, 4),
                entry_deviation_pct=round(entry_deviation_pct, 4),
            )

    return TradeLevelValidation(
        valid=True,
        reason=None,
        risk_pct=round(risk_pct, 4),
        reward_pct=round(reward_pct, 4),
        entry_deviation_pct=round(entry_deviation_pct, 4) if entry_deviation_pct is not None else None,
    )


def _is_actionable(record: dict[str, Any]) -> bool:
    state = str(record.get("trade_state") or "").strip().upper()
    return record.get("is_actionable_now") is True or state in _ACTIONABLE_TRADE_STATES


def _has_bracket_fields(record: dict[str, Any]) -> bool:
    return any(field in record for field in _BRACKET_FIELDS)


def _sanitize_invalid_bracket(
    record: dict[str, Any],
    *,
    reference_price: Any = None,
    explanation_field: str,
) -> tuple[dict[str, Any], bool, bool]:
    sanitized = dict(record)
    if not _has_bracket_fields(sanitized):
        return sanitized, False, False

    values = [sanitized.get(field) for field in _BRACKET_FIELDS]
    was_actionable = _is_actionable(sanitized)
    if all(value is None for value in values) and not was_actionable:
        return sanitized, False, False

    validation = validate_long_trade_levels(
        entry_price=sanitized.get("entry_price"),
        target_price=sanitized.get("target_price"),
        stop_loss_price=sanitized.get("stop_loss_price"),
        reference_price=reference_price,
    )
    sanitized["trade_level_validation"] = validation.to_dict()
    if validation.valid:
        return sanitized, False, False

    reason = validation.reason or "Trade levels failed validation."
    for field in (*_BRACKET_FIELDS, *_DISPLAY_LEVEL_FIELDS):
        if field in sanitized:
            sanitized[field] = None
    sanitized["action_block_reason"] = reason
    if "is_actionable_now" in sanitized or was_actionable:
        sanitized["is_actionable_now"] = False
    if was_actionable:
        sanitized["trade_state"] = INVALID_TRADE_LEVEL_STATE
        sanitized["trade_state_tone"] = "negative"
        sanitized[explanation_field] = reason
        if "recommendation_label" in sanitized:
            sanitized["recommendation_label"] = INVALID_TRADE_LEVEL_STATE
        if "tone" in sanitized:
            sanitized["tone"] = "negative"
    return sanitized, True, was_actionable


def _primary_horizon_key(row: dict[str, Any]) -> str | None:
    label = str(
        row.get("primary_horizon_label")
        or row.get("primary_horizon")
        or row.get("expected_holding_period")
        or row.get("ranking_bucket")
        or ""
    ).lower()
    if "5-15" in label or "swing" in label:
        return "swing_trade"
    if "1-2" in label or "day" in label:
        return "day_trade"
    return None


def apply_scan_trade_level_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a scan payload with malformed or implausible trade levels blocked."""

    protected = deepcopy(payload)
    short_rows: list[dict[str, Any]] = []
    invalid_row_count = 0
    blocked_actionable_count = 0

    for source_row in protected.get("short_term", []):
        if not isinstance(source_row, dict):
            continue
        row = dict(source_row)
        reference_price = row.get("current_price") or row.get("entry_price")
        primary_horizon = _primary_horizon_key(row)
        invalid_horizons: set[str] = set()
        row_had_invalid_levels = False

        for horizon_key in ("day_trade", "swing_trade"):
            horizon = row.get(horizon_key)
            if not isinstance(horizon, dict):
                continue
            sanitized_horizon, invalid, _ = _sanitize_invalid_bracket(
                horizon,
                reference_price=reference_price,
                explanation_field="explanation",
            )
            row[horizon_key] = sanitized_horizon
            if invalid:
                invalid_horizons.add(horizon_key)
                row_had_invalid_levels = True

        row, parent_invalid, parent_blocked = _sanitize_invalid_bracket(
            row,
            reference_price=row.get("current_price"),
            explanation_field="trade_state_explanation",
        )
        row_had_invalid_levels = row_had_invalid_levels or parent_invalid
        primary_invalid = primary_horizon in invalid_horizons
        if primary_invalid and not parent_invalid:
            reason = str(
                row.get(primary_horizon, {}).get("action_block_reason")
                or "The primary trade horizon failed level validation."
            )
            was_actionable = _is_actionable(row)
            for field in (*_BRACKET_FIELDS, *_DISPLAY_LEVEL_FIELDS):
                if field in row:
                    row[field] = None
            row["action_block_reason"] = reason
            row["is_actionable_now"] = False
            row["trade_level_validation"] = {
                "valid": False,
                "reason": reason,
                "risk_pct": None,
                "reward_pct": None,
                "entry_deviation_pct": None,
            }
            if was_actionable:
                row["recommendation_label"] = INVALID_TRADE_LEVEL_STATE
                row["trade_state"] = INVALID_TRADE_LEVEL_STATE
                row["trade_state_tone"] = "negative"
                row["trade_state_explanation"] = reason
                row["tone"] = "negative"
                parent_blocked = True

        if row_had_invalid_levels:
            invalid_row_count += 1
        if parent_blocked:
            blocked_actionable_count += 1
        short_rows.append(row)

    stats = dict(protected.get("market_stats") or {})
    previous_invalid = stats.get("invalid_trade_level_rows")
    previous_blocked = stats.get("blocked_invalid_level_signals")
    stats["invalid_trade_level_rows"] = max(
        invalid_row_count,
        int(previous_invalid) if isinstance(previous_invalid, (int, float)) else 0,
    )
    stats["blocked_invalid_level_signals"] = max(
        blocked_actionable_count,
        int(previous_blocked) if isinstance(previous_blocked, (int, float)) else 0,
    )
    protected["market_stats"] = stats
    protected["short_term"] = short_rows
    return protected


__all__ = [
    "INVALID_TRADE_LEVEL_STATE",
    "MAX_ENTRY_DEVIATION_PCT",
    "MAX_STOP_DISTANCE_PCT",
    "MAX_TARGET_DISTANCE_PCT",
    "TradeLevelValidation",
    "apply_scan_trade_level_policy",
    "validate_long_trade_levels",
]
