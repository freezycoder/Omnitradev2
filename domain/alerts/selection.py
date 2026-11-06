from __future__ import annotations

from typing import Any, Mapping

from domain.alerts.models import AlertKind, MailGate, WeeklySelection


WEEKLY_MIN_SCORE = 80
WEEKLY_LABEL = "Strong Buy"
WEEKLY_CAP = 5
URGENT_MIN_SCORE = 85
URGENT_LABEL = "Strong Setup"
URGENT_CONFIDENCE = "High"
URGENT_STATE = "ENTER NOW"
URGENT_CAP = 2
DAY_HORIZON = "1-2 Day Trade"
SWING_HORIZON = "5-15 Day Swing"
DAY_FAMILY = "short_term_day"
SWING_FAMILY = "short_term_swing"

_SHADOW_IMPACT_FIELDS = (
    "alternative_signal_applied_impact",
    "relative_strength_applied_impact",
    "earnings_intelligence_applied_impact",
)


def mail_gate(payload: Mapping[str, Any], kind: AlertKind) -> MailGate:
    """Allow mail only for a fresh, actionable, live scan."""

    if kind not in {"weekly", "urgent"}:
        return MailGate(False, "unknown_kind")
    source = str(payload.get("source") or "").strip().lower()
    status_raw = payload.get("data_status")
    status = status_raw if isinstance(status_raw, dict) else {}
    data_status = str(status.get("status") or "").strip().lower()
    if source == "demo" or data_status == "demo":
        return MailGate(False, "demo")
    if source == "cached_real":
        return MailGate(False, "cached_real")
    if data_status == "stale":
        return MailGate(False, "stale")
    if source != "live" or data_status != "fresh" or status.get("is_actionable") is not True:
        return MailGate(False, "unavailable" if source != "live" or not status else "not_actionable")
    return MailGate(True, "ok")


def select_weekly(payload: Mapping[str, Any]) -> WeeklySelection:
    qualifying = [
        dict(row)
        for row in _rows(payload, "long_term")
        if _is_strong_buy(row)
    ]
    qualifying.sort(key=_weekly_sort_key)
    return WeeklySelection(shown=tuple(qualifying[:WEEKLY_CAP]), qualifying_count=len(qualifying))


def select_urgent(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    qualifying = [dict(row) for row in _rows(payload, "short_term") if _is_exceptional_setup(row)]
    qualifying.sort(key=_urgent_sort_key)
    return tuple(qualifying[:URGENT_CAP])


def horizon_family(row: Mapping[str, Any]) -> str | None:
    parsed = _horizon(row)
    if parsed is None:
        return None
    family, _score = parsed
    return family


def shadow_applied_is_clean(row: Mapping[str, Any]) -> bool:
    for field in _SHADOW_IMPACT_FIELDS:
        value = row.get(field, 0)
        if value in (None, ""):
            continue
        try:
            if float(value) != 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _is_strong_buy(row: Mapping[str, Any]) -> bool:
    if row.get("recommendation_label") != WEEKLY_LABEL:
        return False
    if not shadow_applied_is_clean(row):
        return False
    score = _as_float(row.get("long_term_score"))
    return score is not None and score >= WEEKLY_MIN_SCORE


def _is_exceptional_setup(row: Mapping[str, Any]) -> bool:
    if not shadow_applied_is_clean(row):
        return False
    if row.get("signal_bucket") != "active":
        return False
    if row.get("is_actionable_now") is not True:
        return False
    if str(row.get("action_block_reason") or "").strip():
        return False
    if row.get("trade_state") != URGENT_STATE:
        return False
    if row.get("recommendation_label") != URGENT_LABEL:
        return False
    if row.get("confidence") != URGENT_CONFIDENCE:
        return False
    primary = _as_float(row.get("short_term_score"))
    horizon = _horizon(row)
    if primary is None or horizon is None:
        return False
    _family, horizon_score = horizon
    return primary >= URGENT_MIN_SCORE and horizon_score >= URGENT_MIN_SCORE


def _horizon(row: Mapping[str, Any]) -> tuple[str, float] | None:
    label = str(row.get("primary_horizon_label") or "")
    if label == DAY_HORIZON:
        nested = row.get("day_trade")
        family = DAY_FAMILY
    elif label == SWING_HORIZON:
        nested = row.get("swing_trade")
        family = SWING_FAMILY
    else:
        return None
    if not isinstance(nested, dict):
        return None
    score = _as_float(nested.get("score"))
    if score is None:
        return None
    return family, score


def _weekly_sort_key(row: Mapping[str, Any]) -> tuple[float, str]:
    score = _as_float(row.get("long_term_score")) or 0.0
    return (-score, str(row.get("ticker") or ""))


def _urgent_sort_key(row: Mapping[str, Any]) -> tuple[float, str]:
    score = _as_float(row.get("short_term_score")) or 0.0
    return (-score, str(row.get("ticker") or ""))


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
