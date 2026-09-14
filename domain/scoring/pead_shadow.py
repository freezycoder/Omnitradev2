from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, timedelta
from typing import Any, Iterable, Sequence

import pandas as pd

from providers.events.sec_edgar_client import SecEventBundle


PEAD_HORIZONS: tuple[int, ...] = (3, 10, 20, 60)
PEAD_EVENT_DATE_SOURCES: tuple[str, ...] = ("sec_filing", "fiscal_period", "unknown")
MARKET_BENCHMARK_SYMBOL = "SPY"
PRICE_STORE_MIN_SESSIONS = 80
MAX_FILING_LAG_DAYS = 120

# Pre-registered size cuts for secondary (descriptive) strata only.
MEGA_CAP_MIN = 200_000_000_000
LARGE_CAP_MIN = 10_000_000_000
MID_CAP_MIN = 2_000_000_000


@dataclass(frozen=True)
class PostEventHorizonReturn:
    sessions: int
    sessions_observed: int
    complete: bool
    stock_return_pct: float | None
    market_return_pct: float | None
    sector_return_pct: float | None
    market_excess_pct: float | None
    sector_excess_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EarningsEventShadow:
    period: str
    event_date: str | None
    event_date_source: str
    surprise_pct: float | None
    surprise_result: str
    sector: str | None
    market_cap: float | None
    size_bucket: str
    market_benchmark_symbol: str
    sector_benchmark_symbol: str | None
    price_history_sessions: int
    market_history_sessions: int
    sector_history_sessions: int
    horizons: list[PostEventHorizonReturn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def horizon(self, sessions: int) -> PostEventHorizonReturn | None:
        for item in self.horizons:
            if item.sessions == sessions:
                return item
        return None


def size_bucket_for_market_cap(market_cap: float | None) -> str:
    if market_cap is None or market_cap <= 0:
        return "unknown"
    if market_cap >= MEGA_CAP_MIN:
        return "mega"
    if market_cap >= LARGE_CAP_MIN:
        return "large"
    if market_cap >= MID_CAP_MIN:
        return "mid"
    return "small"


def close_series(history: pd.DataFrame | None) -> pd.Series:
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().sort_index()
    if close.empty:
        return close
    normalized = close.copy()
    normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
    return normalized


def session_count(history: pd.DataFrame | None) -> int:
    return int(len(close_series(history)))


def horizon_return_pct(
    close: pd.Series,
    event_date: date | None,
    *,
    as_of: date,
    sessions: int,
) -> tuple[float | None, int, bool]:
    if event_date is None or close.empty or sessions <= 0:
        return None, 0, False
    before = close[close.index.date < event_date]
    after = close[(close.index.date >= event_date) & (close.index.date <= as_of)]
    if before.empty or after.empty:
        return None, 0, False
    observed = int(len(after))
    complete = observed >= sessions
    target_index = min(sessions - 1, observed - 1)
    baseline = float(before.iloc[-1])
    target = float(after.iloc[target_index])
    if baseline <= 0:
        return None, observed, False
    return (target / baseline - 1.0) * 100.0, observed, complete


def build_horizon_return(
    *,
    stock_close: pd.Series,
    market_close: pd.Series,
    sector_close: pd.Series,
    event_date: date | None,
    as_of: date,
    sessions: int,
) -> PostEventHorizonReturn:
    stock_return, observed, complete = horizon_return_pct(
        stock_close,
        event_date,
        as_of=as_of,
        sessions=sessions,
    )
    market_return, market_observed, market_complete = horizon_return_pct(
        market_close,
        event_date,
        as_of=as_of,
        sessions=sessions,
    )
    sector_return, sector_observed, sector_complete = horizon_return_pct(
        sector_close,
        event_date,
        as_of=as_of,
        sessions=sessions,
    )
    market_excess = (
        stock_return - market_return
        if stock_return is not None and market_return is not None
        else None
    )
    sector_excess = (
        stock_return - sector_return
        if stock_return is not None and sector_return is not None
        else None
    )
    return PostEventHorizonReturn(
        sessions=sessions,
        sessions_observed=observed,
        complete=complete and stock_return is not None,
        stock_return_pct=_round_optional(stock_return),
        market_return_pct=_round_optional(market_return),
        sector_return_pct=_round_optional(sector_return),
        market_excess_pct=_round_optional(market_excess),
        sector_excess_pct=_round_optional(sector_excess),
    )


def earnings_filing_dates(bundle: SecEventBundle | None) -> list[date]:
    if bundle is None:
        return []
    dates: list[date] = []
    for event in bundle.events:
        if event.category != "earnings_update":
            continue
        parsed = _parse_date(event.filed_at)
        if parsed is not None:
            dates.append(parsed)
    return sorted(set(dates))


def assign_event_date(
    period: str,
    *,
    filing_dates: Sequence[date],
    used_filings: set[date],
) -> tuple[date | None, str]:
    period_date = _parse_date(period)
    if period_date is not None:
        window_end = period_date + timedelta(days=MAX_FILING_LAG_DAYS)
        candidates = [
            filing_date
            for filing_date in filing_dates
            if filing_date not in used_filings
            and period_date <= filing_date <= window_end
        ]
        if candidates:
            chosen = min(candidates)
            used_filings.add(chosen)
            return chosen, "sec_filing"
        return period_date, "fiscal_period"
    return None, "unknown"


def build_event_shadows(
    *,
    quarters: Sequence[Any],
    stock_history: pd.DataFrame,
    market_history: pd.DataFrame | None = None,
    sector_history: pd.DataFrame | None = None,
    sec_bundle: SecEventBundle | None = None,
    as_of: date,
    sector: str | None = None,
    market_cap: float | None = None,
    market_symbol: str = MARKET_BENCHMARK_SYMBOL,
    sector_symbol: str | None = None,
    horizons: Iterable[int] = PEAD_HORIZONS,
) -> list[EarningsEventShadow]:
    stock_close = close_series(stock_history)
    market_close = close_series(market_history)
    sector_close = close_series(sector_history)
    filings = earnings_filing_dates(sec_bundle)
    used_filings: set[date] = set()
    size_bucket = size_bucket_for_market_cap(market_cap)
    events: list[EarningsEventShadow] = []
    ordered = sorted(
        quarters,
        key=lambda quarter: str(getattr(quarter, "period", "")),
        reverse=True,
    )
    for quarter in ordered:
        period = str(getattr(quarter, "period", "") or "")
        event_date, source = assign_event_date(
            period,
            filing_dates=filings,
            used_filings=used_filings,
        )
        surprise = getattr(quarter, "surprise_pct", None)
        result = str(getattr(quarter, "result", "unresolved") or "unresolved")
        horizon_rows = [
            build_horizon_return(
                stock_close=stock_close,
                market_close=market_close,
                sector_close=sector_close,
                event_date=event_date,
                as_of=as_of,
                sessions=int(sessions),
            )
            for sessions in horizons
        ]
        events.append(
            EarningsEventShadow(
                period=period,
                event_date=event_date.isoformat() if event_date else None,
                event_date_source=source,
                surprise_pct=float(surprise) if surprise is not None else None,
                surprise_result=result,
                sector=sector,
                market_cap=float(market_cap) if market_cap is not None else None,
                size_bucket=size_bucket,
                market_benchmark_symbol=market_symbol,
                sector_benchmark_symbol=sector_symbol,
                price_history_sessions=int(len(stock_close)),
                market_history_sessions=int(len(market_close)),
                sector_history_sessions=int(len(sector_close)),
                horizons=horizon_rows,
            )
        )
    events.sort(key=lambda event: event.period, reverse=True)
    return events


def latest_horizons(
    events: Sequence[EarningsEventShadow],
    filing_date: str | None,
) -> list[PostEventHorizonReturn]:
    if not events:
        return []
    if filing_date:
        for event in events:
            if event.event_date == filing_date:
                return list(event.horizons)
    return list(events[0].horizons)


def post_event_horizon_from_dict(payload: dict[str, Any] | None) -> PostEventHorizonReturn | None:
    return _dataclass_from_dict(PostEventHorizonReturn, payload)


def earnings_event_shadow_from_dict(payload: dict[str, Any] | None) -> EarningsEventShadow | None:
    if not isinstance(payload, dict):
        return None
    horizons = [
        horizon
        for row in payload.get("horizons") or []
        if isinstance(row, dict)
        for horizon in [post_event_horizon_from_dict(row)]
        if horizon is not None
    ]
    values = dict(payload)
    values["horizons"] = horizons
    return _dataclass_from_dict(EarningsEventShadow, values)


def _dataclass_from_dict(cls: type[Any], payload: dict[str, Any] | None) -> Any | None:
    if not isinstance(payload, dict):
        return None
    allowed = {item.name for item in fields(cls)}
    values = {key: value for key, value in payload.items() if key in allowed}
    return cls(**values)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else parsed.date()


def _round_optional(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


__all__ = [
    "LARGE_CAP_MIN",
    "MARKET_BENCHMARK_SYMBOL",
    "MAX_FILING_LAG_DAYS",
    "MEGA_CAP_MIN",
    "MID_CAP_MIN",
    "PEAD_EVENT_DATE_SOURCES",
    "PEAD_HORIZONS",
    "PRICE_STORE_MIN_SESSIONS",
    "EarningsEventShadow",
    "PostEventHorizonReturn",
    "assign_event_date",
    "build_event_shadows",
    "build_horizon_return",
    "close_series",
    "earnings_event_shadow_from_dict",
    "earnings_filing_dates",
    "horizon_return_pct",
    "latest_horizons",
    "post_event_horizon_from_dict",
    "session_count",
    "size_bucket_for_market_cap",
]
