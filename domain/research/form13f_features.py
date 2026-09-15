from __future__ import annotations

from collections import defaultdict
from typing import Sequence, assert_never

from config.form13f import (
    CLUSTER_MIN_NOTABLE_MANAGERS,
    ETF_CHURN_PASSIVE_ENTER_THRESHOLD,
    NOTABLE_AUM_FLOOR_USD,
    STREAK_MIN_QUARTERS,
)
from config.form13f_taxonomy_v1 import NAMED_NOTABLE_MANAGERS, PASSIVE_INDEX_MANAGERS, normalize_cik
from providers.events.form13f_models import (
    ClusterEvent,
    Direction,
    HoldingPosition,
    ManagerQuarter,
    StreakEvent,
    parse_iso_date,
)


def quarter_key(reportable_quarter: str) -> tuple[int, int]:
    parsed = parse_iso_date(reportable_quarter)
    if parsed is None:
        raise ValueError(f"Invalid reportable quarter: {reportable_quarter}")
    return parsed.year, (parsed.month - 1) // 3 + 1


def previous_quarter_key(key: tuple[int, int]) -> tuple[int, int]:
    year, quarter = key
    if quarter == 1:
        return year - 1, 4
    return year, quarter - 1


def consecutive_quarters(left: str, right: str) -> bool:
    return previous_quarter_key(quarter_key(right)) == quarter_key(left)


def classify_manager(cik: str, aum_usd: float) -> tuple[bool, bool, str]:
    normalized = normalize_cik(cik)
    if normalized is None:
        return False, False, "missing_cik"
    if normalized in PASSIVE_INDEX_MANAGERS:
        return False, True, "passive_index_exclusion"
    if normalized in NAMED_NOTABLE_MANAGERS:
        return True, False, "named_taxonomy_v1"
    if aum_usd >= NOTABLE_AUM_FLOOR_USD:
        return True, False, "aum_floor"
    return False, False, "below_aum_floor"


def mapped_equity_holdings(holdings: Sequence[HoldingPosition]) -> list[HoldingPosition]:
    rows: list[HoldingPosition] = []
    for row in holdings:
        if not row.ticker:
            continue
        if row.put_call:
            continue
        rows.append(row)
    return rows


def build_manager_quarters(holdings: Sequence[HoldingPosition]) -> list[ManagerQuarter]:
    grouped: dict[tuple[str, str], list[HoldingPosition]] = defaultdict(list)
    for row in mapped_equity_holdings(holdings):
        grouped[(row.manager_cik, row.reportable_quarter)].append(row)
    quarters: list[ManagerQuarter] = []
    for (cik, reportable), rows in grouped.items():
        tickers = tuple(sorted({row.ticker for row in rows if row.ticker}))
        aum = sum(float(row.value_usd or 0.0) for row in rows)
        notable, passive, reason = classify_manager(cik, aum)
        latest = max(rows, key=lambda item: item.filed_at)
        quarters.append(
            ManagerQuarter(
                manager_cik=cik,
                manager_name=latest.manager_name,
                reportable_quarter=reportable,
                filed_at=latest.filed_at,
                aum_usd=round(aum, 2),
                tickers=tickers,
                notable=notable,
                passive=passive,
                notable_reason=reason,
            )
        )
    quarters.sort(key=lambda item: (item.reportable_quarter, item.manager_cik))
    return quarters


def _holdings_by_manager_quarter(
    holdings: Sequence[HoldingPosition],
) -> dict[tuple[str, str], set[str]]:
    grouped: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in mapped_equity_holdings(holdings):
        if row.ticker:
            grouped[(row.manager_cik, row.reportable_quarter)].add(row.ticker.upper())
    return grouped


def detect_position_changes(
    holdings: Sequence[HoldingPosition],
) -> tuple[dict[tuple[str, str], list[ManagerQuarter]], dict[tuple[str, str], list[ManagerQuarter]]]:
    manager_quarters = build_manager_quarters(holdings)
    by_manager: dict[str, list[ManagerQuarter]] = defaultdict(list)
    for row in manager_quarters:
        by_manager[row.manager_cik].append(row)
    entries: dict[tuple[str, str], list[ManagerQuarter]] = defaultdict(list)
    exits: dict[tuple[str, str], list[ManagerQuarter]] = defaultdict(list)
    ticker_sets = _holdings_by_manager_quarter(holdings)
    for cik, rows in by_manager.items():
        ordered = sorted(rows, key=lambda item: item.reportable_quarter)
        seen: dict[tuple[int, int], ManagerQuarter] = {}
        for row in ordered:
            key = quarter_key(row.reportable_quarter)
            prior = seen.get(previous_quarter_key(key))
            seen[key] = row
            if prior is None:
                continue
            current_tickers = ticker_sets.get((cik, row.reportable_quarter), set())
            prior_tickers = ticker_sets.get((cik, prior.reportable_quarter), set())
            for ticker in sorted(current_tickers - prior_tickers):
                entries[(ticker, row.reportable_quarter)].append(row)
            for ticker in sorted(prior_tickers - current_tickers):
                exits[(ticker, row.reportable_quarter)].append(row)
    return entries, exits


def reconstitution_window(reportable_quarter: str) -> str | None:
    parsed = parse_iso_date(reportable_quarter)
    if parsed is None:
        return None
    month = parsed.month
    if month == 6:
        return "russell_and_sp_q2"
    if month in {3, 9, 12}:
        return "sp_quarterly"
    return None


def _kth_filing_date(rows: Sequence[ManagerQuarter], k: int) -> str:
    dates = sorted(row.filed_at for row in rows)
    index = min(max(k - 1, 0), len(dates) - 1)
    return dates[index]


def detect_clusters(
    holdings: Sequence[HoldingPosition],
    *,
    min_notable: int = CLUSTER_MIN_NOTABLE_MANAGERS,
    passive_enter_threshold: int = ETF_CHURN_PASSIVE_ENTER_THRESHOLD,
) -> list[ClusterEvent]:
    entries, exits = detect_position_changes(holdings)
    events: list[ClusterEvent] = []
    events.extend(
        _clusters_for_side(
            entries,
            direction="entry",
            min_notable=min_notable,
            passive_enter_threshold=passive_enter_threshold,
        )
    )
    events.extend(
        _clusters_for_side(
            exits,
            direction="exit",
            min_notable=min_notable,
            passive_enter_threshold=passive_enter_threshold,
        )
    )
    events.sort(key=lambda event: (event.event_date, event.ticker, event.direction))
    return events


def _clusters_for_side(
    changes: dict[tuple[str, str], list[ManagerQuarter]],
    *,
    direction: Direction,
    min_notable: int,
    passive_enter_threshold: int,
) -> list[ClusterEvent]:
    events: list[ClusterEvent] = []
    for (ticker, quarter), rows in changes.items():
        notable = [row for row in rows if row.notable]
        if len({row.manager_cik for row in notable}) < min_notable:
            continue
        unique_notable = _unique_managers(notable)
        passive_count = len({row.manager_cik for row in rows if row.passive})
        window = reconstitution_window(quarter)
        etf_churn = passive_count >= passive_enter_threshold
        if direction == "entry":
            family_direction: Direction = "entry"
        elif direction == "exit":
            family_direction = "exit"
        else:
            assert_never(direction)
        events.append(
            ClusterEvent(
                ticker=ticker,
                direction=family_direction,
                reportable_quarter=quarter,
                event_date=_kth_filing_date(unique_notable, min_notable),
                notable_count=len(unique_notable),
                manager_ciks=tuple(row.manager_cik for row in unique_notable),
                filing_dates=tuple(row.filed_at for row in unique_notable),
                etf_churn_suspect=etf_churn,
                passive_enter_or_exit_count=passive_count,
                reconstitution_window=window,
            )
        )
    return events


def _unique_managers(rows: Sequence[ManagerQuarter]) -> list[ManagerQuarter]:
    unique: dict[str, ManagerQuarter] = {}
    for row in sorted(rows, key=lambda item: (item.filed_at, item.manager_cik)):
        unique.setdefault(row.manager_cik, row)
    return list(unique.values())


def detect_streaks(
    holdings: Sequence[HoldingPosition],
    *,
    min_quarters: int = STREAK_MIN_QUARTERS,
) -> list[StreakEvent]:
    entries, exits = detect_position_changes(holdings)
    net_by_ticker: dict[str, dict[str, int]] = defaultdict(dict)
    filing_by_ticker_quarter: dict[tuple[str, str], list[str]] = defaultdict(list)
    quarters: set[str] = set()
    for (ticker, quarter), rows in entries.items():
        notable = [row for row in rows if row.notable]
        net_by_ticker[ticker][quarter] = net_by_ticker[ticker].get(quarter, 0) + len(
            {row.manager_cik for row in notable}
        )
        filing_by_ticker_quarter[(ticker, quarter)].extend(row.filed_at for row in notable)
        quarters.add(quarter)
    for (ticker, quarter), rows in exits.items():
        notable = [row for row in rows if row.notable]
        net_by_ticker[ticker][quarter] = net_by_ticker[ticker].get(quarter, 0) - len(
            {row.manager_cik for row in notable}
        )
        quarters.add(quarter)

    ordered_quarters = sorted(quarters)
    events: list[StreakEvent] = []
    for ticker, by_quarter in net_by_ticker.items():
        run: list[str] = []
        for quarter in ordered_quarters:
            net_adds = by_quarter.get(quarter, 0)
            if net_adds > 0 and (not run or consecutive_quarters(run[-1], quarter)):
                run.append(quarter)
                continue
            _maybe_append_streak(
                events,
                ticker=ticker,
                quarter_keys=run,
                min_quarters=min_quarters,
                by_quarter=by_quarter,
                filing_by_ticker_quarter=filing_by_ticker_quarter,
            )
            run = [quarter] if net_adds > 0 else []
        _maybe_append_streak(
            events,
            ticker=ticker,
            quarter_keys=run,
            min_quarters=min_quarters,
            by_quarter=by_quarter,
            filing_by_ticker_quarter=filing_by_ticker_quarter,
        )
    events.sort(key=lambda event: (event.event_date, event.ticker))
    return events


def _maybe_append_streak(
    events: list[StreakEvent],
    *,
    ticker: str,
    quarter_keys: list[str],
    min_quarters: int,
    by_quarter: dict[str, int],
    filing_by_ticker_quarter: dict[tuple[str, str], list[str]],
) -> None:
    if len(quarter_keys) < min_quarters:
        return
    completing = quarter_keys[-1]
    filing_dates = sorted(filing_by_ticker_quarter.get((ticker, completing), []))
    if not filing_dates:
        return
    events.append(
        StreakEvent(
            ticker=ticker,
            reportable_quarter=completing,
            event_date=filing_dates[-1],
            quarters=len(quarter_keys),
            quarter_keys=tuple(quarter_keys),
            net_notable_adds=int(by_quarter.get(completing, 0)),
        )
    )


def primary_cluster_events(events: Sequence[ClusterEvent]) -> list[ClusterEvent]:
    return [
        event
        for event in events
        if event.direction == "entry" and not event.etf_churn_suspect
    ]


def single_holder_entries(
    holdings: Sequence[HoldingPosition],
) -> list[tuple[str, str, str]]:
    entries, _exits = detect_position_changes(holdings)
    rows: list[tuple[str, str, str]] = []
    for (ticker, quarter), managers in entries.items():
        notable = _unique_managers([row for row in managers if row.notable])
        if len(notable) != 1:
            continue
        rows.append((ticker, quarter, notable[0].filed_at))
    return rows


def event_date_is_lag_correct(event_date: str, reportable_quarter: str, *, min_lag_days: int = 40) -> bool:
    filed = parse_iso_date(event_date)
    period_end = parse_iso_date(reportable_quarter)
    if filed is None or period_end is None:
        return False
    return (filed - period_end).days >= min_lag_days


__all__ = [
    "build_manager_quarters",
    "classify_manager",
    "consecutive_quarters",
    "detect_clusters",
    "detect_position_changes",
    "detect_streaks",
    "event_date_is_lag_correct",
    "mapped_equity_holdings",
    "primary_cluster_events",
    "quarter_key",
    "reconstitution_window",
    "single_holder_entries",
]
