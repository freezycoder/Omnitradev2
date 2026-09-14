from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Sequence

from config.section16 import (
    CLUSTER_MIN_INSIDER_VALUE_USD,
    CLUSTER_MIN_INSIDERS,
    CLUSTER_WINDOW_DAYS,
    STREAK_MIN_CONSECUTIVE_WEEKS,
    STREAK_MIN_VALUE_USD,
)
from providers.events.section16_models import ClusterEvent, InsiderTransaction, StreakEvent, parse_iso_date


def eligible_open_market_rows(
    transactions: Sequence[InsiderTransaction],
) -> list[InsiderTransaction]:
    rows: list[InsiderTransaction] = []
    for row in transactions:
        if row.is_derivative:
            continue
        if row.transaction_code not in {"P", "S"}:
            continue
        if row.is_10b5_1:
            continue
        if not row.ticker or not row.filed_at:
            continue
        rows.append(row)
    return rows


def _owner_key(row: InsiderTransaction) -> str:
    return (row.owner_cik or row.owner_name or row.accession_number).strip()


def detect_clusters(
    transactions: Sequence[InsiderTransaction],
    *,
    as_of: date | None = None,
    min_insiders: int = CLUSTER_MIN_INSIDERS,
    window_days: int = CLUSTER_WINDOW_DAYS,
    min_insider_value_usd: float = CLUSTER_MIN_INSIDER_VALUE_USD,
) -> list[ClusterEvent]:
    rows = eligible_open_market_rows(transactions)
    if as_of is not None:
        window_start = as_of - timedelta(days=window_days - 1)
        rows = [
            row
            for row in rows
            if (parsed := parse_iso_date(row.filed_at)) is not None
            and window_start <= parsed <= as_of
        ]
    grouped: dict[tuple[str, str], list[InsiderTransaction]] = defaultdict(list)
    for row in rows:
        direction = row.direction
        if direction is None:
            continue
        grouped[(row.ticker.upper(), direction)].append(row)

    events: list[ClusterEvent] = []
    for (ticker, direction), group in grouped.items():
        by_owner: dict[str, list[InsiderTransaction]] = defaultdict(list)
        for row in group:
            by_owner[_owner_key(row)].append(row)
        qualifying_owners = {
            owner: owner_rows
            for owner, owner_rows in by_owner.items()
            if sum(abs(float(item.value_usd or 0.0)) for item in owner_rows) >= min_insider_value_usd
        }
        if len(qualifying_owners) < min_insiders:
            continue
        filed_dates = [parse_iso_date(row.filed_at) for row in group]
        valid_dates = [item for item in filed_dates if item is not None]
        if not valid_dates:
            continue
        as_of_date = as_of or max(valid_dates)
        events.append(
            ClusterEvent(
                ticker=ticker,
                direction=direction,
                as_of=as_of_date.isoformat(),
                window_start=(as_of_date - timedelta(days=window_days - 1)).isoformat(),
                insider_count=len(qualifying_owners),
                insider_ciks=tuple(sorted(qualifying_owners)),
                total_value_usd=round(sum(abs(float(row.value_usd or 0.0)) for row in group), 2),
                accession_numbers=tuple(sorted({row.accession_number for row in group})),
            )
        )
    events.sort(key=lambda event: (event.as_of, event.ticker, event.direction))
    return events


def detect_streaks(
    transactions: Sequence[InsiderTransaction],
    *,
    as_of: date | None = None,
    min_weeks: int = STREAK_MIN_CONSECUTIVE_WEEKS,
    min_value_usd: float = STREAK_MIN_VALUE_USD,
) -> list[StreakEvent]:
    rows = eligible_open_market_rows(transactions)
    if as_of is not None:
        rows = [
            row
            for row in rows
            if (parsed := parse_iso_date(row.filed_at)) is not None and parsed <= as_of
        ]
    grouped: dict[tuple[str, str, str], list[InsiderTransaction]] = defaultdict(list)
    for row in rows:
        direction = row.direction
        if direction is None:
            continue
        grouped[(row.ticker.upper(), _owner_key(row), direction)].append(row)

    events: list[StreakEvent] = []
    for (ticker, owner, direction), group in grouped.items():
        weeks: dict[str, float] = defaultdict(float)
        owner_name = next((row.owner_name for row in group if row.owner_name), None)
        for row in group:
            filed = parse_iso_date(row.filed_at)
            if filed is None:
                continue
            iso_year, iso_week, _ = filed.isocalendar()
            week_key = f"{iso_year:04d}-W{iso_week:02d}"
            weeks[week_key] += abs(float(row.value_usd or 0.0))
        ordered_weeks = sorted(weeks)
        if not ordered_weeks:
            continue
        run: list[str] = []
        for week_key in ordered_weeks:
            if run and _weeks_are_consecutive(run[-1], week_key):
                run.append(week_key)
            else:
                _maybe_append_streak(
                    events,
                    ticker=ticker,
                    owner_cik=owner,
                    owner_name=owner_name,
                    direction=direction,
                    week_keys=run,
                    week_values=weeks,
                    min_weeks=min_weeks,
                    min_value_usd=min_value_usd,
                    as_of=as_of,
                )
                run = [week_key]
        _maybe_append_streak(
            events,
            ticker=ticker,
            owner_cik=owner,
            owner_name=owner_name,
            direction=direction,
            week_keys=run,
            week_values=weeks,
            min_weeks=min_weeks,
            min_value_usd=min_value_usd,
            as_of=as_of,
        )
    events.sort(key=lambda event: (event.as_of, event.ticker, event.owner_cik))
    return events


def _weeks_are_consecutive(previous: str, current: str) -> bool:
    previous_date = _week_start(previous)
    current_date = _week_start(current)
    if previous_date is None or current_date is None:
        return False
    return (current_date - previous_date).days == 7


def _week_start(week_key: str) -> date | None:
    try:
        year_text, week_text = week_key.split("-W")
        return date.fromisocalendar(int(year_text), int(week_text), 1)
    except (TypeError, ValueError):
        return None


def _maybe_append_streak(
    events: list[StreakEvent],
    *,
    ticker: str,
    owner_cik: str,
    owner_name: str | None,
    direction: str,
    week_keys: list[str],
    week_values: dict[str, float],
    min_weeks: int,
    min_value_usd: float,
    as_of: date | None,
) -> None:
    if len(week_keys) < min_weeks:
        return
    streak_value = sum(week_values[week_key] for week_key in week_keys)
    if streak_value < min_value_usd:
        return
    last_week = _week_start(week_keys[-1])
    if last_week is None:
        return
    events.append(
        StreakEvent(
            ticker=ticker,
            owner_cik=owner_cik,
            owner_name=owner_name,
            direction=direction,  # type: ignore[arg-type]
            as_of=(as_of or last_week).isoformat(),
            weeks=len(week_keys),
            streak_value_usd=round(streak_value, 2),
            week_keys=tuple(week_keys),
        )
    )


def net_intensity(
    transactions: Sequence[InsiderTransaction],
    *,
    ticker: str | None = None,
    as_of: date | None = None,
    lookback_days: int | None = None,
) -> tuple[float, float]:
    rows = eligible_open_market_rows(transactions)
    if ticker:
        rows = [row for row in rows if row.ticker.upper() == ticker.upper()]
    if as_of is not None:
        start = as_of if lookback_days is None else as_of - timedelta(days=lookback_days - 1)
        rows = [
            row
            for row in rows
            if (parsed := parse_iso_date(row.filed_at)) is not None and start <= parsed <= as_of
        ]
    return (
        round(sum(row.signed_value_usd for row in rows), 2),
        round(sum(row.signed_shares for row in rows), 4),
    )


__all__ = [
    "detect_clusters",
    "detect_streaks",
    "eligible_open_market_rows",
    "net_intensity",
]
