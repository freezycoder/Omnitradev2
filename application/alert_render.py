"""Plain-text bodies for the weekly digest and the rare review alert."""

from __future__ import annotations

from typing import Any

from domain.alerts.disclaimer import MAIL_BAR_SENTENCE, RESEARCH_CTA, footer, require_disclaimer
from domain.alerts.models import AlertIntent, RenderedMessage


def render_intent(intent: AlertIntent, *, sender: str, recipients: tuple[str, ...]) -> RenderedMessage:
    if intent.kind == "urgent":
        text = _urgent_text(intent)
        subject = f"OmniTrade review: {_ticker(intent.rows[0])} exceptional setup"
        urgent = True
    elif intent.kind == "weekly_quiet":
        text = _quiet_text(intent)
        subject = "OmniTrade weekly · no Strong Buys"
        urgent = False
    else:
        text = _digest_text(intent)
        subject = f"OmniTrade weekly · {len(intent.rows)} Strong Buys"
        urgent = False
    require_disclaimer(text, urgent=urgent)
    return RenderedMessage(
        sender=sender,
        recipients=recipients,
        subject=subject,
        text=text,
        dedupe_key=intent.dedupe_key,
    )


def _digest_text(intent: AlertIntent) -> str:
    shown = len(intent.rows)
    lines = [
        "OmniTrade weekly",
        _status_line(intent, extra=f"showing {shown} of {intent.qualifying_count} Strong Buys"),
        "",
    ]
    for index, row in enumerate(intent.rows, start=1):
        lines.extend(_long_term_block(index, row))
        lines.append("")
    overflow = intent.qualifying_count - shown
    if overflow > 0:
        lines.append(f"{overflow} additional Strong Buys are in the scanner.")
        lines.append("")
    lines.extend(_book_lines(intent))
    lines.append(footer(urgent=False))
    return "\n".join(lines).rstrip() + "\n"


def _quiet_text(intent: AlertIntent) -> str:
    lines = [
        "OmniTrade weekly",
        _status_line(intent),
        "The live scan found no Strong Buys.",
        "",
        *_book_lines(intent),
        footer(urgent=False),
    ]
    return "\n".join(lines)


def _urgent_text(intent: AlertIntent) -> str:
    row = intent.rows[0]
    lines = [
        "OmniTrade review",
        _status_line(intent),
        "",
        RESEARCH_CTA,
        "",
        f"{_ticker(row)} — {_text(row.get('company_name'))}",
        f"Setup: {_text(row.get('setup_type'))}",
        f"Regime: {_text(row.get('setup_regime'))}",
        f"Horizon: {_text(row.get('primary_horizon_label'))}",
        (
            f"Score {_number(row.get('short_term_score'))} · "
            f"{_text(row.get('recommendation_label'))} · {_text(row.get('confidence'))}"
        ),
        f"State: {_text(row.get('trade_state'))}",
        f"Last price: {_price(row.get('current_price'))}",
        (
            "Signal levels (not a fill): "
            f"entry {_price(row.get('entry_price'))} · "
            f"stop {_price(row.get('stop_loss_price'))} · "
            f"target {_price(row.get('target_price'))}"
        ),
        "",
        MAIL_BAR_SENTENCE,
        "",
        "Thesis:",
        *_bullets(row.get("reasons")),
        f"Invalidation: {_text(row.get('invalidation_note'))}",
        "",
        footer(urgent=True),
    ]
    return "\n".join(lines)


def _long_term_block(index: int, row: dict[str, Any]) -> list[str]:
    lines = [
        f"{index}. {_ticker(row)} — {_text(row.get('company_name'))} ({_text(row.get('sector'))})",
        (
            f"Score {_number(row.get('long_term_score'))} · "
            f"{_text(row.get('recommendation_label'))} · {_text(row.get('confidence'))}"
        ),
        f"Last price: {_price(row.get('current_price'))}",
        "Thesis:",
        *_bullets(row.get("key_strengths") or [row.get("thesis")]),
        "Risks:",
        *_bullets(row.get("key_risks")),
    ]
    accounting = _text(row.get("accounting_explanation"), default="")
    label = _text(row.get("accounting_label"), default="")
    if accounting or label:
        lines.append(f"Accounting: {label} {accounting}".strip())
    return lines


def _book_lines(intent: AlertIntent) -> list[str]:
    if not intent.book_notes:
        return []
    return [*intent.book_notes, ""]


def _status_line(intent: AlertIntent, extra: str = "") -> str:
    parts = [
        f"source={intent.source}",
        f"captured_at={intent.captured_at or 'unavailable'}",
        f"universe={intent.universe_size}",
    ]
    if extra:
        parts.append(extra)
    return " · ".join(parts)


def _bullets(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [f"- {value.strip()}"]
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            return [f"- {item}" for item in items]
    return ["- unavailable"]


def _ticker(row: dict[str, Any]) -> str:
    return str(row.get("ticker") or "").upper() or "UNKNOWN"


def _text(value: Any, default: str = "unavailable") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "unavailable"
    if number.is_integer():
        return str(int(number))
    return f"{number:.1f}"


def _price(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "unavailable"
