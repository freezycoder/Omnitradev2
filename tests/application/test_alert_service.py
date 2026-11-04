from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from application.alert_render import render_intent
from application.alert_service import AlertConfig, AlertService
from domain.alerts.disclaimer import PULLBACK_SENTENCE, RESEARCH_CTA
from domain.alerts.models import RenderedMessage, SendResult
from domain.portfolio.book_analysis import BookHolding
from storage.repositories.email_dispatch_repository import MemoryEmailDispatchRepository
from tests.domain.alerts.test_selection import _live, _long, _short


WEEKLY_NOW = datetime(2026, 10, 18, 17, 30, tzinfo=timezone.utc)
TUESDAY_AFTER_MISS = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
URGENT_NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)
BEFORE_OPEN = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class FakeMailer:
    def __init__(self, results: list[SendResult] | None = None) -> None:
        self.results = list(results or [])
        self.sent: list[RenderedMessage] = []

    def send(self, message: RenderedMessage) -> SendResult:
        self.sent.append(message)
        if self.results:
            return self.results.pop(0)
        return SendResult(message_id=f"msg-{len(self.sent)}", retryable=False)


def test_weekly_digest_omits_buys_and_caps_names() -> None:
    rows = [_long(ticker, 90 - index, "Strong Buy") for index, ticker in enumerate(
        ["MSFT", "AAPL", "NVDA", "AMZN", "META", "AVGO"]
    )]
    rows.append(_long("JPM", 99, "Buy"))
    rows.append(_long("XOM", 40, "Avoid"))
    mailer = FakeMailer()
    result = _service(mailer, _live(long_rows=rows)).run("weekly")

    assert result.exit_code == 0
    body = mailer.sent[0].text
    assert mailer.sent[0].subject == "OmniTrade weekly · 5 Strong Buys"
    assert "showing 5 of 6 Strong Buys" in body
    assert "1 additional Strong Buys are in the scanner." in body
    assert "JPM" not in body
    assert "XOM" not in body
    assert "Signal levels" not in body
    assert PULLBACK_SENTENCE not in body
    assert "Decision support, not financial advice, and not a broker." in body


def test_quiet_week_sends_a_note_without_a_name_list() -> None:
    mailer = FakeMailer()
    result = _service(mailer, _live(long_rows=[_long("JPM", 70, "Buy")])).run("weekly")

    assert result.exit_code == 0
    assert len(mailer.sent) == 1
    assert mailer.sent[0].subject == "OmniTrade weekly · no Strong Buys"
    assert "The live scan found no Strong Buys." in mailer.sent[0].text
    assert "JPM" not in mailer.sent[0].text


def test_same_iso_week_sends_one_weekly_mail() -> None:
    mailer = FakeMailer()
    service = _service(mailer, _live(long_rows=[_long("AAPL", 88, "Strong Buy")]))
    assert service.run("weekly").exit_code == 0
    assert service.run("weekly").exit_code == 0
    assert len(mailer.sent) == 1


def test_a_quiet_note_blocks_a_later_digest_the_same_week() -> None:
    payloads = [
        _live(long_rows=[_long("JPM", 70, "Buy")]),
        _live(long_rows=[_long("AAPL", 90, "Strong Buy")]),
    ]

    def scan_fn(**kwargs):
        return payloads.pop(0)

    mailer = FakeMailer()
    service = _service(mailer, {}, scan_fn=scan_fn)
    assert service.run("weekly").exit_code == 0
    assert service.run("weekly").exit_code == 0
    assert len(mailer.sent) == 1
    assert mailer.sent[0].subject == "OmniTrade weekly · no Strong Buys"


def test_exceptional_setup_sends_review_mail_with_pullback_sentence() -> None:
    mailer = FakeMailer()
    result = _service(mailer, _live(short_rows=[_short("NVDA", 91)]), now=URGENT_NOW).run("urgent")

    assert result.exit_code == 0
    message = mailer.sent[0]
    assert message.subject == "OmniTrade review: NVDA exceptional setup"
    assert RESEARCH_CTA in message.text
    assert PULLBACK_SENTENCE in message.text
    assert "The mail bar is a short-term score of at least 85." in message.text
    assert "Signal levels (not a fill): entry 100.00 · stop 97.00 · target 106.00" in message.text


def test_scores_below_85_and_non_buy_states_do_not_send() -> None:
    payload = _live(
        short_rows=[
            _short("AAPL", 84),
            _short("MSFT", 75),
            _short("AMZN", 72),
            _short("META", 90, recommendation_label="Watchlist"),
            _short("JPM", 90, trade_state="WAIT FOR PULLBACK", actionable=False, bucket="waiting"),
            _short("XOM", 90, trade_state="CONFIRMED BREAKDOWN — SELL"),
        ]
    )
    mailer = FakeMailer()
    result = _service(mailer, payload, now=URGENT_NOW).run("urgent")

    assert result.exit_code == 0
    assert result.suppressed_reason == "empty"
    assert mailer.sent == []


def test_shadow_impact_drops_the_row() -> None:
    payload = _live(short_rows=[_short("COST", 95, alternative_signal_applied_impact=7)])
    mailer = FakeMailer()
    result = _service(mailer, payload, now=URGENT_NOW).run("urgent")
    assert result.suppressed_reason == "empty"
    assert mailer.sent == []


def test_same_urgent_key_sends_once() -> None:
    mailer = FakeMailer()
    service = _service(mailer, _live(short_rows=[_short("NVDA", 90)]), now=URGENT_NOW)
    assert service.run("urgent").exit_code == 0
    assert service.run("urgent").exit_code == 0
    assert len(mailer.sent) == 1
    assert mailer.sent[0].dedupe_key.startswith("urgent|NVDA|short_term_day|ENTER NOW|2026-10-14|")


def test_timeout_stays_pending_and_retry_reuses_the_idempotency_key() -> None:
    mailer = FakeMailer(
        [
            SendResult(message_id=None, retryable=True, error="timeout"),
            SendResult(message_id="msg-retried", retryable=False),
        ]
    )
    service = _service(mailer, _live(short_rows=[_short("NVDA", 90)]), now=URGENT_NOW)
    first = service.run("urgent")
    second = service.run("urgent")

    assert first.exit_code == 1
    assert second.exit_code == 0
    assert [message.dedupe_key for message in mailer.sent] == [mailer.sent[0].dedupe_key, mailer.sent[0].dedupe_key]
    stored = service.ledger.get(mailer.sent[0].dedupe_key)
    assert stored is not None
    assert stored.status == "sent"
    assert stored.provider_message_id == "msg-retried"


def test_client_error_fails_and_stops_after_three_attempts() -> None:
    mailer = FakeMailer([SendResult(message_id=None, retryable=False, error="invalid_from")] * 4)
    service = _service(mailer, _live(short_rows=[_short("NVDA", 90)]), now=URGENT_NOW)
    for _ in range(3):
        assert service.run("urgent").exit_code == 1
    assert len(mailer.sent) == 3
    fourth = service.run("urgent")
    assert fourth.exit_code == 0
    assert len(mailer.sent) == 3
    stored = next(record for record in service.ledger.rows.values() if record.status == "failed")
    assert stored.attempt_count == 3
    assert stored.last_error == "invalid_from"


def test_missing_disclaimer_does_not_call_transport() -> None:
    mailer = FakeMailer()

    def bad_render(intent, *, sender: str, recipients: tuple[str, ...]) -> RenderedMessage:
        return RenderedMessage(
            sender=sender,
            recipients=recipients,
            subject="OmniTrade review: NVDA exceptional setup",
            text="Buy this now.",
            dedupe_key=intent.dedupe_key,
        )

    service = _service(
        mailer,
        _live(short_rows=[_short("NVDA", 90)]),
        now=URGENT_NOW,
        render_fn=bad_render,
    )
    result = service.run("urgent")
    assert result.exit_code == 1
    assert mailer.sent == []
    failed = next(record for record in service.ledger.rows.values() if record.kind == "urgent")
    assert failed.status == "failed"
    assert failed.last_error == "disclaimer"


def test_non_live_scans_suppress_both_kinds_without_sending() -> None:
    mailer = FakeMailer()
    cases = [
        _live(source="demo", status="demo", actionable=False, long_rows=[_long("AAPL", 90, "Strong Buy")]),
        _live(status="stale", actionable=False, long_rows=[_long("AAPL", 90, "Strong Buy")]),
        {"source": "live", "long_term": [_long("AAPL", 90, "Strong Buy")], "short_term": []},
        _live(source="cached_real", long_rows=[_long("AAPL", 90, "Strong Buy")]),
    ]
    for payload in cases:
        service = _service(mailer, payload)
        weekly = service.run("weekly")
        urgent_service = _service(mailer, payload, now=URGENT_NOW)
        urgent = urgent_service.run("urgent")
        assert weekly.exit_code == 1
        assert urgent.exit_code == 1
    assert mailer.sent == []


def test_urgent_outside_the_cash_session_does_not_scan() -> None:
    calls: list[dict] = []

    def scan_fn(**kwargs):
        calls.append(kwargs)
        return _live(short_rows=[_short("NVDA", 95)])

    service = _service(FakeMailer(), _live(), now=BEFORE_OPEN, scan_fn=scan_fn)
    result = service.run("urgent")
    assert result.window_skipped is True
    assert result.exit_code == 0
    assert calls == []


def test_urgent_does_not_scan_on_a_full_holiday_or_after_an_early_close() -> None:
    ny = ZoneInfo("America/New_York")
    closed_times = [
        datetime(2026, 11, 26, 15, 0, tzinfo=ny),
        datetime(2026, 11, 27, 14, 0, tzinfo=ny),
        datetime(2026, 7, 3, 11, 0, tzinfo=ny),
    ]
    for now in closed_times:
        calls: list[dict] = []

        def scan_fn(**kwargs):
            calls.append(kwargs)
            return _live(short_rows=[_short("NVDA", 95)])

        result = _service(FakeMailer(), _live(), now=now, scan_fn=scan_fn).run("urgent")
        assert result.window_skipped is True
        assert calls == []


def test_tuesday_sends_last_sundays_iso_week() -> None:
    mailer = FakeMailer()
    result = _service(
        mailer,
        _live(long_rows=[_long("AAPL", 88, "Strong Buy")]),
        now=TUESDAY_AFTER_MISS,
    ).run("weekly")

    assert result.exit_code == 0
    assert result.due_week == "2026-W44"
    assert mailer.sent[0].dedupe_key.startswith("weekly|2026-W44|")
    assert result.window_skipped is False


def test_already_sent_week_skips_the_scan_on_a_weekday() -> None:
    calls: list[dict] = []

    def scan_fn(**kwargs):
        calls.append(kwargs)
        return _live(long_rows=[_long("AAPL", 88, "Strong Buy")])

    service = _service(FakeMailer(), _live(), now=TUESDAY_AFTER_MISS, scan_fn=scan_fn)
    first = service.run("weekly")
    second = service.run("weekly")

    assert first.exit_code == 0
    assert first.due_week == "2026-W44"
    assert second.already_sent is True
    assert second.due_week == "2026-W44"
    assert len(calls) == 1


def test_sunday_before_eighteen_still_catches_up_the_previous_week() -> None:
    london = ZoneInfo("Europe/London")
    before_hour = datetime(2026, 11, 8, 17, 0, tzinfo=london)
    mailer = FakeMailer()
    result = _service(
        mailer,
        _live(long_rows=[_long("AAPL", 88, "Strong Buy")]),
        now=before_hour,
    ).run("weekly")

    assert result.exit_code == 0
    assert result.due_week == "2026-W44"
    assert mailer.sent[0].dedupe_key.startswith("weekly|2026-W44|")


def test_weekly_mail_includes_the_saved_book() -> None:
    mailer = FakeMailer()
    service = _service(
        mailer,
        _live(
            long_rows=[
                _long("AAPL", 88, "Strong Buy"),
                _long("XOM", 40, "Avoid", sector="Energy"),
            ]
        ),
        book_loader=lambda: (BookHolding("AAPL", 30), BookHolding("XOM", 10)),
    )
    result = service.run("weekly")

    assert result.exit_code == 0
    text = mailer.sent[0].text
    assert "Your portfolio" in text
    assert "Trim, then keep the core" in text or "Do not treat this mix as the core" in text
    assert "Trim AAPL from 30.0% toward 20%." in text
    assert "Review XOM before keeping 10.0%." in text
    assert "Decision support, not financial advice, and not a broker." in text


def test_a_broken_book_does_not_block_the_weekly_mail() -> None:
    def broken() -> tuple[BookHolding, ...]:
        raise RuntimeError("ledger down")

    mailer = FakeMailer()
    result = _service(
        mailer,
        _live(long_rows=[_long("AAPL", 88, "Strong Buy")]),
        book_loader=broken,
    ).run("weekly")

    assert result.exit_code == 0
    assert "Your portfolio" not in mailer.sent[0].text


def test_weekly_due_reports_an_overdue_week() -> None:
    due = _service(FakeMailer(), _live(), now=TUESDAY_AFTER_MISS).weekly_due()
    assert due.iso_week == "2026-W44"
    assert due.sent is False


def test_alert_scan_passes_allow_demo_fallback_false() -> None:
    calls: list[dict] = []

    def scan_fn(**kwargs):
        calls.append(kwargs)
        return _live(long_rows=[_long("AAPL", 88, "Strong Buy")])

    _service(FakeMailer(), _live(), scan_fn=scan_fn).run("weekly")
    assert calls == [{"data_mode": "live", "allow_demo_fallback": False}]


def test_recent_live_scan_is_reused_for_urgent_mail() -> None:
    calls: list[dict] = []

    def scan_fn(**kwargs):
        calls.append(kwargs)
        return _live(short_rows=[_short("NVDA", 90)])

    service = _service(FakeMailer(), _live(), now=URGENT_NOW, scan_fn=scan_fn)
    service.run("urgent")
    service.run("urgent")
    assert len(calls) == 1


def _service(
    mailer: FakeMailer,
    payload: dict,
    *,
    now: datetime = WEEKLY_NOW,
    scan_fn=None,
    render_fn=None,
    book_loader=None,
):
    def default_scan(**kwargs):
        return payload

    return AlertService(
        config=AlertConfig(
            resend_api_key="re_test",
            alert_from="OmniTrade research <alerts@example.com>",
            alert_recipients=("operator@example.com",),
            alert_timezone="Europe/London",
        ),
        ledger=MemoryEmailDispatchRepository(),
        mailer=mailer,
        scan_fn=scan_fn or default_scan,
        clock=lambda: now,
        render_fn=render_fn or render_intent,
        book_loader=book_loader,
    )
