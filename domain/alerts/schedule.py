from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from domain.alerts.dedupe import NY_ZONE


REGULAR_CLOSE_MINUTE = 16 * 60
EARLY_CLOSE_MINUTE = 13 * 60
OPEN_MINUTE = 9 * 60 + 30


def in_ny_cash_session(now: datetime) -> bool:
    """True while the NYSE cash session is open, including early-close days."""

    local = now.astimezone(NY_ZONE)
    close_minute = session_close_minute(local.date())
    if close_minute is None:
        return False
    minutes = local.hour * 60 + local.minute
    return OPEN_MINUTE <= minutes <= close_minute


def session_close_minute(day: date) -> int | None:
    """Return the cash-session close, or None when the NYSE is fully closed."""

    if day.weekday() >= 5 or day in full_close_dates(day.year):
        return None
    if day in early_close_dates(day.year):
        return EARLY_CLOSE_MINUTE
    return REGULAR_CLOSE_MINUTE


def in_weekly_send_hour(now: datetime, timezone_name: str) -> bool:
    """True on Sunday between 18:00 and 18:59 in the operator timezone."""

    local = now.astimezone(ZoneInfo(timezone_name))
    return local.weekday() == 6 and local.hour == 18


def last_weekly_deadline(now: datetime, timezone_name: str) -> datetime:
    """Most recent Sunday 18:00 in the operator timezone that is not in the future."""

    zone = ZoneInfo(timezone_name)
    local = now.astimezone(zone)
    days_since_sunday = (local.weekday() + 1) % 7
    sunday = local.date() - timedelta(days=days_since_sunday)
    deadline = datetime.combine(sunday, time(18, 0), tzinfo=zone)
    if local < deadline:
        deadline -= timedelta(days=7)
    return deadline


def full_close_dates(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter_sunday(year) - timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }
    new_year = _observed(date(year + 1, 1, 1))
    if new_year.year == year:
        holidays.add(new_year)
    return {day for day in holidays if day.year == year}


def early_close_dates(year: int) -> set[date]:
    closed = full_close_dates(year)
    thanksgiving = _nth_weekday(year, 11, 3, 4)
    candidates = {
        thanksgiving + timedelta(days=1),
        date(year, 7, 3),
        date(year, 12, 24),
    }
    return {day for day in candidates if day.weekday() < 5 and day not in closed and day.year == year}


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        probe = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        probe = date(year, month + 1, 1) - timedelta(days=1)
    return probe - timedelta(days=(probe.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    """Anonymous Gregorian algorithm."""

    century, year_in_century = divmod(year, 100)
    century_leap, century_remainder = divmod(century, 4)
    year_leap, year_remainder = divmod(year_in_century, 4)
    lunar_cycle = year % 19
    epact_century = (century + 8) // 25
    epact_correction = (century - epact_century + 1) // 3
    epact = (19 * lunar_cycle + century - century_leap - epact_correction + 15) % 30
    weekday_offset = (32 + 2 * century_remainder + 2 * year_leap - epact - year_remainder) % 7
    month_correction = (lunar_cycle + 11 * epact + 22 * weekday_offset) // 451
    month, day_index = divmod(epact + weekday_offset - 7 * month_correction + 114, 31)
    return date(year, month, day_index + 1)
