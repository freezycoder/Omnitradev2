from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from domain.alerts.schedule import in_ny_cash_session, last_weekly_deadline


NY = ZoneInfo("America/New_York")
LONDON = ZoneInfo("Europe/London")


def test_regular_wednesday_session_bounds() -> None:
    assert in_ny_cash_session(datetime(2026, 10, 14, 9, 30, tzinfo=NY)) is True
    assert in_ny_cash_session(datetime(2026, 10, 14, 16, 0, tzinfo=NY)) is True
    assert in_ny_cash_session(datetime(2026, 10, 14, 9, 29, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 10, 14, 16, 1, tzinfo=NY)) is False


def test_full_holidays_and_early_closes_are_not_a_normal_session() -> None:
    assert in_ny_cash_session(datetime(2026, 4, 3, 11, 0, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 7, 3, 11, 0, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 11, 26, 15, 0, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 12, 25, 10, 0, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 11, 27, 12, 0, tzinfo=NY)) is True
    assert in_ny_cash_session(datetime(2026, 11, 27, 13, 0, tzinfo=NY)) is True
    assert in_ny_cash_session(datetime(2026, 11, 27, 13, 1, tzinfo=NY)) is False
    assert in_ny_cash_session(datetime(2026, 12, 24, 12, 0, tzinfo=NY)) is True
    assert in_ny_cash_session(datetime(2026, 12, 24, 13, 1, tzinfo=NY)) is False


def test_last_weekly_deadline_is_the_most_recent_sunday_eighteen() -> None:
    assert last_weekly_deadline(
        datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc),
        "Europe/London",
    ) == datetime(2026, 11, 1, 18, 0, tzinfo=LONDON)
    assert last_weekly_deadline(
        datetime(2026, 11, 1, 17, 59, tzinfo=LONDON),
        "Europe/London",
    ) == datetime(2026, 10, 25, 18, 0, tzinfo=LONDON)
    assert last_weekly_deadline(
        datetime(2026, 11, 1, 18, 0, tzinfo=LONDON),
        "Europe/London",
    ) == datetime(2026, 11, 1, 18, 0, tzinfo=LONDON)
