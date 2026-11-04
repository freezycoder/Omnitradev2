from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


AlertKind = Literal["weekly", "urgent"]
IntentKind = Literal["weekly_digest", "weekly_quiet", "urgent"]
DispatchStatus = Literal["pending", "sent", "suppressed", "failed"]
WEEKLY_DISPATCH_KINDS = frozenset({"weekly_digest", "weekly_quiet"})


@dataclass(frozen=True)
class MailGate:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class WeeklySelection:
    shown: tuple[dict[str, Any], ...]
    qualifying_count: int


@dataclass(frozen=True)
class AlertIntent:
    kind: IntentKind
    dedupe_key: str
    ticker: str | None
    strategy_family: str | None
    signal_date: str
    payload_hash: str
    rows: tuple[dict[str, Any], ...]
    qualifying_count: int
    universe_name: str
    universe_size: int
    captured_at: str | None
    source: str
    book_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DispatchRecord:
    dedupe_key: str
    kind: str
    ticker: str | None
    strategy_family: str | None
    signal_date: str
    payload_hash: str
    status: DispatchStatus
    provider_message_id: str | None
    attempt_count: int
    last_error: str | None
    created_at: str
    sent_at: str | None


@dataclass(frozen=True)
class RenderedMessage:
    sender: str
    recipients: tuple[str, ...]
    subject: str
    text: str
    dedupe_key: str


@dataclass(frozen=True)
class SendResult:
    message_id: str | None
    retryable: bool
    error: str | None = None


@dataclass(frozen=True)
class WeeklyDue:
    iso_week: str
    deadline: datetime
    sent: bool


@dataclass(frozen=True)
class AlertRunResult:
    exit_code: int
    sent_keys: tuple[str, ...] = ()
    preview: tuple[RenderedMessage, ...] = ()
    suppressed_reason: str | None = None
    window_skipped: bool = False
    already_sent: bool = False
    due_week: str | None = None
