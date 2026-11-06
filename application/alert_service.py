from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Protocol

from application.alert_render import render_intent
from application.alert_scan import ScanFunction, load_alert_payload
from domain.alerts.dedupe import (
    iso_week_label,
    ny_session_date,
    payload_fingerprint,
    urgent_dedupe_key,
    weekly_dedupe_key,
)
from domain.alerts.disclaimer import DisclaimerMissing, disclaimer_is_present
from domain.alerts.models import (
    AlertIntent,
    AlertKind,
    AlertRunResult,
    RenderedMessage,
    SendResult,
    WeeklyDue,
)
from domain.alerts.schedule import in_ny_cash_session, last_weekly_deadline
from domain.alerts.selection import horizon_family, mail_gate, select_urgent, select_weekly
from domain.portfolio.book_analysis import BookHolding, analyze_book
from storage.repositories.email_dispatch_repository import EmailDispatchRepository, new_record

log = logging.getLogger(__name__)


Clock = Callable[[], datetime]
RenderFunction = Callable[..., RenderedMessage]
BookLoader = Callable[[], tuple[BookHolding, ...]]
HeldRowsFn = Callable[[tuple[BookHolding, ...], list[dict[str, Any]]], list[dict[str, Any]]]


def _scanner_rows_only(
    holdings: tuple[BookHolding, ...], long_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return long_rows


@dataclass(frozen=True)
class AlertConfig:
    resend_api_key: str
    alert_from: str
    alert_recipients: tuple[str, ...]
    alert_timezone: str


class MailSender(Protocol):
    def send(self, message: RenderedMessage) -> SendResult: ...


class AlertService:
    def __init__(
        self,
        *,
        config: AlertConfig,
        ledger: EmailDispatchRepository,
        mailer: MailSender,
        scan_fn: ScanFunction,
        clock: Clock,
        render_fn: RenderFunction = render_intent,
        book_loader: BookLoader | None = None,
        held_rows: HeldRowsFn = _scanner_rows_only,
    ) -> None:
        self.config = config
        self.ledger = ledger
        self.mailer = mailer
        self.scan_fn = scan_fn
        self.clock = clock
        self.render_fn = render_fn
        self.book_loader = book_loader
        self.held_rows = held_rows

    def run(self, kind: AlertKind, *, dry_run: bool = False) -> AlertRunResult:
        recipients = self.config.alert_recipients
        if not 1 <= len(recipients) <= 10:
            return AlertRunResult(exit_code=1, suppressed_reason="recipients")
        if not dry_run and (not self.config.resend_api_key or not self.config.alert_from):
            return AlertRunResult(exit_code=1, suppressed_reason="mail_config")

        now = _aware(self.clock())
        due_week: str | None = None
        if kind == "weekly":
            due = self.weekly_due(now)
            due_week = due.iso_week
            if not dry_run and due.sent:
                return AlertRunResult(exit_code=0, already_sent=True, due_week=due_week)
        elif not dry_run and not in_ny_cash_session(now):
            return AlertRunResult(exit_code=0, window_skipped=True)

        payload = load_alert_payload(kind=kind, ledger=self.ledger, now=now, scan_fn=self.scan_fn)
        gate = mail_gate(payload, kind)
        if not gate.allowed:
            if not dry_run:
                self._record_suppressed(kind, gate.reason, now)
            return AlertRunResult(exit_code=1, suppressed_reason=gate.reason, due_week=due_week)

        intents = self._intents(kind, payload, now, iso_week=due_week)
        if kind == "urgent" and not intents:
            if not dry_run:
                self._record_suppressed(kind, "empty", now)
            return AlertRunResult(exit_code=0, suppressed_reason="empty")

        previews: list[RenderedMessage] = []
        sent: list[str] = []
        exit_code = 0
        for intent in intents:
            if dry_run:
                previews.append(
                    self.render_fn(
                        intent,
                        sender=self.config.alert_from,
                        recipients=recipients,
                    )
                )
                continue
            outcome, key = self._dispatch(intent, now)
            if outcome == "sent":
                sent.append(key)
            elif outcome in {"failed", "pending"}:
                exit_code = 1
        return AlertRunResult(
            exit_code=exit_code,
            sent_keys=tuple(sent),
            preview=tuple(previews),
            due_week=due_week,
        )

    def weekly_due(self, now: datetime | None = None) -> WeeklyDue:
        moment = _aware(now or self.clock())
        deadline = last_weekly_deadline(moment, self.config.alert_timezone)
        iso_week = iso_week_label(deadline, self.config.alert_timezone)
        record = self.ledger.find_weekly(iso_week)
        sent = record is not None and record.status == "sent"
        return WeeklyDue(iso_week=iso_week, deadline=deadline, sent=sent)

    def _intents(
        self,
        kind: AlertKind,
        payload: dict[str, Any],
        now: datetime,
        *,
        iso_week: str | None = None,
    ) -> tuple[AlertIntent, ...]:
        universe_name = str(payload.get("universe_name") or "default")
        shared = {
            "universe_name": universe_name,
            "universe_size": _universe_size(payload),
            "captured_at": _captured_at(payload),
            "source": "live",
        }
        if kind == "weekly":
            selection = select_weekly(payload)
            variant = "digest" if selection.shown else "quiet"
            iso_week = iso_week or iso_week_label(
                last_weekly_deadline(now, self.config.alert_timezone),
                self.config.alert_timezone,
            )
            return (
                AlertIntent(
                    kind="weekly_digest" if selection.shown else "weekly_quiet",
                    dedupe_key=weekly_dedupe_key(
                        iso_week=iso_week,
                        universe_name=universe_name,
                    ),
                    ticker=None,
                    strategy_family="long_term",
                    signal_date=iso_week,
                    payload_hash=payload_fingerprint(variant, selection.shown),
                    rows=selection.shown,
                    qualifying_count=selection.qualifying_count,
                    book_notes=self._book_notes(payload),
                    **shared,
                ),
            )
        session_date = ny_session_date(now)
        intents: list[AlertIntent] = []
        for row in select_urgent(payload):
            family = horizon_family(row)
            if family is None:
                continue
            ticker = str(row.get("ticker") or "").upper()
            intents.append(
                AlertIntent(
                    kind="urgent",
                    dedupe_key=urgent_dedupe_key(
                        ticker=ticker,
                        family=family,
                        session_date=session_date,
                    ),
                    ticker=ticker,
                    strategy_family=family,
                    signal_date=session_date,
                    payload_hash=payload_fingerprint("urgent", (row,)),
                    rows=(row,),
                    qualifying_count=1,
                    **shared,
                )
            )
        return tuple(intents)

    def _book_notes(self, payload: dict[str, Any]) -> tuple[str, ...]:
        if self.book_loader is None:
            return ()
        try:
            holdings = self.book_loader()
        except Exception:
            log.exception("operator book could not be loaded")
            return ()
        if not holdings:
            return ()
        long_rows = payload.get("long_term")
        short_rows = payload.get("short_term")
        scanner_rows = long_rows if isinstance(long_rows, list) else []
        try:
            book_rows = self.held_rows(holdings, scanner_rows)
        except Exception:
            log.exception("held tickers could not be scored for the weekly mail")
            book_rows = scanner_rows
        analysis = analyze_book(
            holdings,
            book_rows,
            short_rows if isinstance(short_rows, list) else [],
        )
        return analysis.mail_lines()

    def _dispatch(self, intent: AlertIntent, now: datetime) -> tuple[str, str]:
        existing = self.ledger.get(intent.dedupe_key)
        if existing is not None and existing.status == "sent":
            return "skipped", intent.dedupe_key
        if existing is not None and existing.attempt_count >= 3 and existing.status in {"pending", "failed"}:
            return "stopped", intent.dedupe_key

        created_at = now.astimezone(timezone.utc).isoformat()
        if existing is None:
            record = new_record(
                dedupe_key=intent.dedupe_key,
                kind=intent.kind,
                ticker=intent.ticker,
                strategy_family=intent.strategy_family,
                signal_date=intent.signal_date,
                payload_hash=intent.payload_hash,
                status="pending",
                created_at=created_at,
                attempt_count=1,
            )
            try:
                self.ledger.insert(record)
            except KeyError:
                return "skipped", intent.dedupe_key
        else:
            record = replace(
                existing,
                status="pending",
                attempt_count=existing.attempt_count + 1,
                last_error=None,
            )
            self.ledger.save(record)

        try:
            message = self.render_fn(
                intent,
                sender=self.config.alert_from,
                recipients=self.config.alert_recipients,
            )
        except DisclaimerMissing:
            self.ledger.save(replace(record, status="failed", last_error="disclaimer"))
            return "failed", intent.dedupe_key
        if not disclaimer_is_present(message.text, urgent=intent.kind == "urgent"):
            self.ledger.save(replace(record, status="failed", last_error="disclaimer"))
            return "failed", intent.dedupe_key

        message = replace(message, dedupe_key=intent.dedupe_key)
        result = self.mailer.send(message)
        if result.message_id:
            self.ledger.save(
                replace(
                    record,
                    status="sent",
                    provider_message_id=result.message_id,
                    sent_at=created_at,
                    last_error=None,
                )
            )
            return "sent", intent.dedupe_key
        if result.retryable:
            self.ledger.save(replace(record, status="pending", last_error=result.error))
            return "pending", intent.dedupe_key
        self.ledger.save(replace(record, status="failed", last_error=result.error))
        return "failed", intent.dedupe_key

    def _record_suppressed(self, kind: str, reason: str, now: datetime) -> None:
        stamp = now.astimezone(timezone.utc).isoformat()
        try:
            self.ledger.insert(
                new_record(
                    dedupe_key=f"suppressed|{kind}|{reason}|{stamp}",
                    kind=kind,
                    ticker=None,
                    strategy_family=None,
                    signal_date=stamp,
                    payload_hash="suppressed",
                    status="suppressed",
                    created_at=stamp,
                    last_error=reason,
                )
            )
        except KeyError:
            return


def _aware(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _universe_size(payload: dict[str, Any]) -> int:
    universe = payload.get("universe")
    if isinstance(universe, list):
        return len(universe)
    return 0


def _captured_at(payload: dict[str, Any]) -> str | None:
    status = payload.get("data_status")
    if isinstance(status, dict) and status.get("captured_at"):
        return str(status["captured_at"])
    updated = payload.get("updated_at")
    return str(updated) if updated else None
