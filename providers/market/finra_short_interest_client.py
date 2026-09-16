from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from threading import RLock
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config.finra_short_interest import (
    API_BASE_URL,
    API_LIMIT,
    CACHE_DIR,
    CACHE_TTL_SECONDS,
    DATASET_GROUP,
    DATASET_NAME,
    FALLBACK_DATASET_NAME,
    PROVENANCE,
    PUBLICATION_LAG_BUSINESS_DAYS,
    TIMEOUT_SECONDS,
)
from config.settings import settings
from storage.cache.json_cache import ensure_parent, load_json, save_json


_log = logging.getLogger(__name__)
_CACHE_LOCK = RLock()
_REQUEST_LOCK = RLock()
_MEMORY_CYCLE_CACHE: dict[str, tuple[float, "FinraShortInterestCycle"]] = {}
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL_SECONDS = 0.12

FetchBytes = Callable[[str, bytes | None], bytes]

SYMBOL_FIELDS = (
    "symbolCode",
    "securitiesInformationProcessorSymbolIdentifier",
    "issueSymbolIdentifier",
)
SHORT_SHARES_FIELDS = (
    "currentShortPositionQuantity",
    "currentShortShareNumber",
)
PREVIOUS_SHARES_FIELDS = (
    "previousShortPositionQuantity",
    "previousShortShareNumber",
)
DAYS_TO_COVER_FIELDS = (
    "daysToCoverQuantity",
    "daysToCoverNumber",
)
PCT_CHANGE_FIELDS = ("changePercent",)
SETTLEMENT_FIELDS = (
    "settlementDate",
    "accountingDate",
    "accountingYearMonthNumber",
)
ADV_FIELDS = (
    "averageDailyVolumeQuantity",
    "averageShortShareNumber",
)


def nth_weekday_after(start: date, n: int) -> date:
    """Return the n-th weekday (Mon–Fri) strictly after ``start``.

    FINRA publishes on the 7th business day after settlement. This helper
    counts weekdays only. Exchange holidays are not in this calendar, so a
    holiday can move the official publication date later by one or two
    sessions. Event dating still uses this lag model rather than settlement.
    """

    if n <= 0:
        raise ValueError("Publication lag must be a positive weekday count.")
    cursor = start
    remaining = n
    while remaining > 0:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            remaining -= 1
    return cursor


def publication_date_from_settlement(
    settlement: date,
    *,
    lag_business_days: int = PUBLICATION_LAG_BUSINESS_DAYS,
) -> date:
    return nth_weekday_after(settlement, lag_business_days)


def _previous_weekday(value: date) -> date:
    cursor = value
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def mid_month_settlement(year: int, month: int) -> date:
    """Rule 4560 mid-month settlement: the 15th, or prior weekday if weekend."""

    return _previous_weekday(date(year, month, 15))


def month_end_settlement(year: int, month: int) -> date:
    """Rule 4560 month-end settlement: last weekday of the month."""

    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    return _previous_weekday(first_of_next - timedelta(days=1))


def designated_settlement_dates(start: date, end: date) -> tuple[date, ...]:
    dates: list[date] = []
    year, month = start.year, start.month
    while date(year, month, 1) <= date(end.year, end.month, 1):
        for candidate in (mid_month_settlement(year, month), month_end_settlement(year, month)):
            if start <= candidate <= end:
                dates.append(candidate)
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return tuple(sorted(set(dates)))


def latest_published_settlement(as_of: date | None = None) -> date | None:
    """Latest Rule 4560 settlement whose weekday publication date is on or before as_of."""

    today = as_of or date.today()
    lookback_start = date(today.year - 1, today.month, 1)
    published = [
        settlement
        for settlement in designated_settlement_dates(lookback_start, today)
        if publication_date_from_settlement(settlement) <= today
    ]
    if not published:
        return None
    return published[-1]


def _first_present(payload: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _parse_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _parse_settlement(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(int(value))
        if len(text) == 8:
            try:
                return datetime.strptime(text, "%Y%m%d").date()
            except ValueError:
                return None
        return None
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d-%b-%y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class FinraShortInterestRow:
    symbol: str
    settlement_date: date
    publication_date: date
    short_shares: float
    previous_short_shares: float | None
    pct_change_prior: float | None
    days_to_cover: float | None
    average_daily_volume: float | None
    issue_name: str | None = None
    market_class_code: str | None = None
    revision_flag: str | None = None
    stock_split_flag: str | None = None
    dataset: str = DATASET_NAME
    provenance: str = PROVENANCE
    source: str = ""

    @property
    def event_date(self) -> date:
        return self.publication_date

    @property
    def lag_calendar_days(self) -> int:
        return (self.publication_date - self.settlement_date).days

    @property
    def log_short_shares(self) -> float | None:
        if self.short_shares < 0:
            return None
        return math.log1p(self.short_shares)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["settlement_date"] = self.settlement_date.isoformat()
        payload["publication_date"] = self.publication_date.isoformat()
        payload["event_date"] = self.event_date.isoformat()
        payload["lag_calendar_days"] = self.lag_calendar_days
        payload["log_short_shares"] = self.log_short_shares
        payload["feature_family"] = "short_interest"
        payload["not_short_volume"] = True
        payload["pct_float"] = None
        payload["pct_float_status"] = "deferred"
        return payload


@dataclass(frozen=True)
class FinraShortInterestCycle:
    settlement_date: date
    publication_date: date
    dataset: str
    provenance: str
    source_url: str
    rows: tuple[FinraShortInterestRow, ...] = field(default_factory=tuple)
    status: str = "available"
    message: str | None = None

    def row_for_symbol(self, symbol: str) -> FinraShortInterestRow | None:
        needle = symbol.upper().strip()
        for row in self.rows:
            if row.symbol == needle:
                return row
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "settlement_date": self.settlement_date.isoformat(),
            "publication_date": self.publication_date.isoformat(),
            "event_date": self.publication_date.isoformat(),
            "dataset": self.dataset,
            "provenance": self.provenance,
            "source_url": self.source_url,
            "status": self.status,
            "message": self.message,
            "row_count": len(self.rows),
            "feature_family": "short_interest",
            "not_short_volume": True,
        }


def parse_short_interest_record(
    payload: Mapping[str, Any],
    *,
    dataset: str = DATASET_NAME,
    source: str = "",
) -> FinraShortInterestRow | None:
    symbol_raw = _first_present(payload, SYMBOL_FIELDS)
    symbol = str(symbol_raw or "").upper().strip()
    settlement = _parse_settlement(_first_present(payload, SETTLEMENT_FIELDS))
    short_shares = _parse_number(_first_present(payload, SHORT_SHARES_FIELDS))
    if not symbol or settlement is None or short_shares is None or short_shares < 0:
        return None
    previous = _parse_number(_first_present(payload, PREVIOUS_SHARES_FIELDS))
    pct_change = _parse_number(_first_present(payload, PCT_CHANGE_FIELDS))
    days_to_cover = _parse_number(_first_present(payload, DAYS_TO_COVER_FIELDS))
    if days_to_cover is not None and days_to_cover < 0:
        days_to_cover = None
    return FinraShortInterestRow(
        symbol=symbol,
        settlement_date=settlement,
        publication_date=publication_date_from_settlement(settlement),
        short_shares=float(short_shares),
        previous_short_shares=previous,
        pct_change_prior=pct_change,
        days_to_cover=days_to_cover,
        average_daily_volume=_parse_number(_first_present(payload, ADV_FIELDS)),
        issue_name=str(payload["issueName"]).strip() if payload.get("issueName") else None,
        market_class_code=(
            str(payload["marketClassCode"]).strip()
            if payload.get("marketClassCode")
            else str(payload.get("marketCategoryCode") or "").strip() or None
        ),
        revision_flag=str(payload["revisionFlag"]).strip() if payload.get("revisionFlag") else None,
        stock_split_flag=(
            str(payload["stockSplitFlag"]).strip() if payload.get("stockSplitFlag") else None
        ),
        dataset=dataset,
        provenance=PROVENANCE,
        source=source,
    )


def parse_short_interest_records(
    records: Iterable[Mapping[str, Any]],
    *,
    dataset: str = DATASET_NAME,
    source: str = "",
) -> tuple[FinraShortInterestRow, ...]:
    rows = [
        row
        for row in (
            parse_short_interest_record(item, dataset=dataset, source=source)
            for item in records
        )
        if row is not None
    ]
    rows.sort(key=lambda item: (item.settlement_date, item.symbol))
    return tuple(rows)


def _user_agent() -> str:
    declared = settings.sec_edgar_user_agent.strip()
    if declared:
        return declared
    return "OmniTrade/1.0 (non-commercial research; FINRA equity short interest)"


def dataset_url(dataset: str = DATASET_NAME) -> str:
    return f"{API_BASE_URL.rstrip('/')}/{DATASET_GROUP}/name/{dataset}"


def _default_fetch_bytes(url: str, body: bytes | None) -> bytes:
    request = Request(
        url,
        data=body,
        method="POST" if body is not None else "GET",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": _user_agent(),
        },
    )
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


class FinraShortInterestClient:
    """Ingests FINRA Rule 4560 biweekly short interest.

    Event dates are publication dates (7th weekday after settlement), not
    settlement dates. This is position-level short interest, not daily
    CNMS short-sale volume.
    """

    def __init__(
        self,
        *,
        cache_ttl_seconds: int = CACHE_TTL_SECONDS,
        cache_dir: Any = CACHE_DIR,
        fetch_bytes: FetchBytes | None = None,
        dataset: str = DATASET_NAME,
    ) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_dir = cache_dir
        self._fetch_bytes = fetch_bytes
        self.dataset = dataset

    def fetch_settlement(
        self,
        settlement: date,
        *,
        dataset: str | None = None,
    ) -> FinraShortInterestCycle:
        dataset_name = dataset or self.dataset
        cache_key = f"{dataset_name}:{settlement.isoformat()}"
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _MEMORY_CYCLE_CACHE.get(cache_key)
            if cached and now - cached[0] <= self.cache_ttl_seconds:
                return cached[1]

        disk_path = self.cache_dir / f"{dataset_name}_{settlement.strftime('%Y%m%d')}.json"
        disk_payload = load_json(disk_path, default=None)
        if isinstance(disk_payload, list) and disk_payload:
            cycle = self._cycle_from_records(
                disk_payload,
                settlement=settlement,
                dataset=dataset_name,
                source_url=dataset_url(dataset_name),
            )
            with _CACHE_LOCK:
                _MEMORY_CYCLE_CACHE[cache_key] = (time.monotonic(), cycle)
            return cycle

        records = self._fetch_settlement_records(settlement, dataset=dataset_name)
        if not records and dataset_name == DATASET_NAME:
            records = self._fetch_settlement_records(
                settlement,
                dataset=FALLBACK_DATASET_NAME,
            )
            if records:
                dataset_name = FALLBACK_DATASET_NAME
        if records:
            try:
                ensure_parent(disk_path)
                save_json(disk_path, records)
            except OSError:
                _log.warning("Could not persist FINRA SI cache to %s.", disk_path, exc_info=True)
        cycle = self._cycle_from_records(
            records,
            settlement=settlement,
            dataset=dataset_name,
            source_url=dataset_url(dataset_name),
        )
        with _CACHE_LOCK:
            _MEMORY_CYCLE_CACHE[cache_key] = (time.monotonic(), cycle)
        return cycle

    def get_latest_cycle(self, *, as_of: date | None = None) -> FinraShortInterestCycle:
        settlement = latest_published_settlement(as_of)
        if settlement is None:
            today = as_of or date.today()
            return FinraShortInterestCycle(
                settlement_date=today,
                publication_date=publication_date_from_settlement(today),
                dataset=self.dataset,
                provenance=PROVENANCE,
                source_url=dataset_url(self.dataset),
                status="unavailable",
                message="No Rule 4560 settlement has reached its publication date.",
            )
        return self.fetch_settlement(settlement)

    def get_latest_row(self, ticker: str, *, as_of: date | None = None) -> FinraShortInterestRow | None:
        cycle = self.get_latest_cycle(as_of=as_of)
        if cycle.status != "available":
            return None
        return cycle.row_for_symbol(ticker)

    def fetch_symbol_history(
        self,
        ticker: str,
        start: date,
        end: date,
        *,
        dataset: str | None = None,
    ) -> tuple[FinraShortInterestRow, ...]:
        dataset_name = dataset or self.dataset
        symbol = ticker.upper().strip()
        body = {
            "compareFilters": [
                {"compareType": "EQUAL", "fieldName": "symbolCode", "fieldValue": symbol},
            ],
            "dateRangeFilters": [
                {
                    "fieldName": "settlementDate",
                    "startDate": start.isoformat(),
                    "endDate": end.isoformat(),
                }
            ],
            "limit": API_LIMIT,
        }
        records = self._post_paginated(dataset_url(dataset_name), body)
        if not records and dataset_name == DATASET_NAME:
            body["compareFilters"][0]["fieldName"] = (
                "securitiesInformationProcessorSymbolIdentifier"
            )
            records = self._post_paginated(dataset_url(FALLBACK_DATASET_NAME), body)
            dataset_name = FALLBACK_DATASET_NAME if records else dataset_name
        return parse_short_interest_records(records, dataset=dataset_name, source=dataset_url(dataset_name))

    def _cycle_from_records(
        self,
        records: list[Mapping[str, Any]],
        *,
        settlement: date,
        dataset: str,
        source_url: str,
    ) -> FinraShortInterestCycle:
        rows = parse_short_interest_records(records, dataset=dataset, source=source_url)
        publication = publication_date_from_settlement(settlement)
        if not rows:
            return FinraShortInterestCycle(
                settlement_date=settlement,
                publication_date=publication,
                dataset=dataset,
                provenance=PROVENANCE,
                source_url=source_url,
                status="unavailable",
                message=f"No FINRA short-interest rows for settlement {settlement.isoformat()}.",
            )
        return FinraShortInterestCycle(
            settlement_date=settlement,
            publication_date=publication,
            dataset=dataset,
            provenance=PROVENANCE,
            source_url=source_url,
            rows=rows,
            status="available",
        )

    def _fetch_settlement_records(
        self,
        settlement: date,
        *,
        dataset: str,
    ) -> list[dict[str, Any]]:
        body = {
            "compareFilters": [
                {
                    "compareType": "EQUAL",
                    "fieldName": "settlementDate",
                    "fieldValue": settlement.isoformat(),
                }
            ],
            "limit": API_LIMIT,
        }
        return self._post_paginated(dataset_url(dataset), body)

    def _post_paginated(self, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            page_body = dict(body)
            page_body["offset"] = offset
            page_body["limit"] = int(body.get("limit") or API_LIMIT)
            raw = self._post(url, json.dumps(page_body).encode("utf-8"))
            if raw is None:
                break
            if not raw.strip():
                break
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                _log.warning("FINRA SI response was not JSON for %s.", url)
                break
            if not isinstance(parsed, list) or not parsed:
                break
            records.extend(item for item in parsed if isinstance(item, dict))
            if len(parsed) < page_body["limit"]:
                break
            offset += page_body["limit"]
            if offset > 250_000:
                break
        return records

    def _post(self, url: str, body: bytes) -> bytes | None:
        global _LAST_REQUEST_AT
        with _REQUEST_LOCK:
            wait_seconds = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            try:
                raw = self._fetch(url, body)
            except HTTPError as exc:
                _LAST_REQUEST_AT = time.monotonic()
                if exc.code in {204, 404}:
                    return b""
                _log.warning("FINRA SI fetch failed for %s (%s).", url, exc.code)
                return None
            except (URLError, TimeoutError, OSError):
                _log.warning("FINRA SI fetch error for %s.", url, exc_info=True)
                return None
            _LAST_REQUEST_AT = time.monotonic()
        return raw

    def _fetch(self, url: str, body: bytes | None) -> bytes:
        if self._fetch_bytes is not None:
            return self._fetch_bytes(url, body)
        return _default_fetch_bytes(url, body)


def build_finra_short_interest_client() -> FinraShortInterestClient:
    return FinraShortInterestClient()


def reset_finra_short_interest_caches() -> None:
    with _CACHE_LOCK:
        _MEMORY_CYCLE_CACHE.clear()


__all__ = [
    "FinraShortInterestClient",
    "FinraShortInterestCycle",
    "FinraShortInterestRow",
    "build_finra_short_interest_client",
    "designated_settlement_dates",
    "latest_published_settlement",
    "mid_month_settlement",
    "month_end_settlement",
    "nth_weekday_after",
    "parse_short_interest_record",
    "parse_short_interest_records",
    "publication_date_from_settlement",
    "reset_finra_short_interest_caches",
]
