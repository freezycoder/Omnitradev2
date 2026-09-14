from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from threading import RLock
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from config.settings import (
    FINRA_REGSHO_CACHE_DIR,
    FINRA_REGSHO_CACHE_TTL_SECONDS,
    FINRA_REGSHO_DAILY_BASE_URL,
    FINRA_REGSHO_FACILITY,
    FINRA_REGSHO_TIMEOUT_SECONDS,
    FINRA_SHORT_VOLUME_PROVENANCE,
    settings,
)
from storage.cache.json_cache import ensure_parent


_log = logging.getLogger(__name__)
_CACHE_LOCK = RLock()
_REQUEST_LOCK = RLock()
_MEMORY_FILE_CACHE: dict[str, tuple[float, str | None]] = {}
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL_SECONDS = 0.12

FetchBytes = Callable[[str], bytes]

REQUIRED_COLUMNS = (
    "Date",
    "Symbol",
    "ShortVolume",
    "ShortExemptVolume",
    "TotalVolume",
    "Market",
)


@dataclass(frozen=True)
class FinraShortVolumeRow:
    as_of_date: date
    symbol: str
    short_volume: float
    short_exempt_volume: float
    total_volume: float
    market: str
    provenance: str = FINRA_SHORT_VOLUME_PROVENANCE
    facility: str = FINRA_REGSHO_FACILITY
    source_file: str = ""

    @property
    def short_ratio(self) -> float | None:
        if self.total_volume <= 0:
            return None
        return self.short_volume / self.total_volume

    @property
    def exempt_share(self) -> float | None:
        if self.total_volume <= 0:
            return None
        return self.short_exempt_volume / self.total_volume

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["as_of_date"] = self.as_of_date.isoformat()
        payload["short_ratio"] = self.short_ratio
        payload["exempt_share"] = self.exempt_share
        payload["exchange_short_volume_included"] = False
        payload["feature_family"] = "short_volume"
        payload["not_short_interest"] = True
        return payload


@dataclass(frozen=True)
class FinraDailyFile:
    as_of_date: date
    facility: str
    provenance: str
    source_url: str
    rows: tuple[FinraShortVolumeRow, ...] = field(default_factory=tuple)
    status: str = "available"
    message: str | None = None

    def row_for_symbol(self, symbol: str) -> FinraShortVolumeRow | None:
        needle = symbol.upper().strip()
        for row in self.rows:
            if row.symbol == needle:
                return row
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "facility": self.facility,
            "provenance": self.provenance,
            "source_url": self.source_url,
            "status": self.status,
            "message": self.message,
            "row_count": len(self.rows),
            "exchange_short_volume_included": False,
            "feature_family": "short_volume",
            "not_short_interest": True,
        }


def daily_file_url(as_of: date, *, facility: str = FINRA_REGSHO_FACILITY) -> str:
    stamp = as_of.strftime("%Y%m%d")
    return f"{FINRA_REGSHO_DAILY_BASE_URL.rstrip('/')}/{facility}shvol{stamp}.txt"


def _parse_yyyymmdd(value: str) -> date | None:
    text = value.strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_number(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_regsho_text(
    payload: str,
    *,
    source_url: str = "",
    facility: str = FINRA_REGSHO_FACILITY,
) -> tuple[FinraShortVolumeRow, ...]:
    lines = [line.strip() for line in payload.splitlines() if line.strip()]
    if not lines:
        return ()
    header = [part.strip() for part in lines[0].split("|")]
    if header[:6] != list(REQUIRED_COLUMNS):
        raise ValueError(
            f"Unexpected FINRA Reg SHO header {header!r}; expected {list(REQUIRED_COLUMNS)}."
        )
    aggregated: dict[tuple[date, str], list[float | str]] = {}
    for line in lines[1:]:
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 6:
            continue
        as_of = _parse_yyyymmdd(parts[0])
        symbol = parts[1].upper().strip()
        short_volume = _parse_number(parts[2])
        short_exempt_volume = _parse_number(parts[3])
        total_volume = _parse_number(parts[4])
        market = parts[5]
        if as_of is None or not symbol or short_volume is None or total_volume is None:
            continue
        if short_exempt_volume is None:
            short_exempt_volume = 0.0
        key = (as_of, symbol)
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = [short_volume, short_exempt_volume, total_volume, market]
            continue
        existing[0] = float(existing[0]) + short_volume
        existing[1] = float(existing[1]) + short_exempt_volume
        existing[2] = float(existing[2]) + total_volume
        markets = {token for token in str(existing[3]).split(",") if token} | {
            token for token in market.split(",") if token
        }
        existing[3] = ",".join(sorted(markets))
    rows = [
        FinraShortVolumeRow(
            as_of_date=as_of,
            symbol=symbol,
            short_volume=float(values[0]),
            short_exempt_volume=float(values[1]),
            total_volume=float(values[2]),
            market=str(values[3]),
            provenance=FINRA_SHORT_VOLUME_PROVENANCE,
            facility=facility,
            source_file=source_url,
        )
        for (as_of, symbol), values in sorted(aggregated.items())
    ]
    return tuple(rows)


def _user_agent() -> str:
    declared = settings.sec_edgar_user_agent.strip()
    if declared:
        return declared
    return "OmniTrade/1.0 (non-commercial research; FINRA short-sale volume)"


def _default_fetch_bytes(url: str, *, timeout_seconds: int) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "text/plain, */*",
            "User-Agent": _user_agent(),
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


class FinraShortVolumeClient:
    """Ingests FINRA CNMS Reg SHO daily short-volume files.

    These files cover TRF/ADF/ORF (off-exchange) activity only. They are not
    bi-monthly short interest and are not consolidated with exchange short volume.
    """

    def __init__(
        self,
        *,
        timeout_seconds: int = FINRA_REGSHO_TIMEOUT_SECONDS,
        cache_ttl_seconds: int = FINRA_REGSHO_CACHE_TTL_SECONDS,
        cache_dir: Any = FINRA_REGSHO_CACHE_DIR,
        fetch_bytes: FetchBytes | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.cache_dir = cache_dir
        self._fetch_bytes = fetch_bytes

    def fetch_daily_file(self, as_of: date, *, facility: str = FINRA_REGSHO_FACILITY) -> FinraDailyFile:
        url = daily_file_url(as_of, facility=facility)
        text = self._read_daily_text(as_of, facility=facility, url=url)
        if text is None:
            return FinraDailyFile(
                as_of_date=as_of,
                facility=facility,
                provenance=FINRA_SHORT_VOLUME_PROVENANCE,
                source_url=url,
                status="unavailable",
                message=(
                    f"FINRA {facility} short-volume file for {as_of.isoformat()} was not available. "
                    "Exchange short volume is never present in this feed."
                ),
            )
        rows = parse_regsho_text(text, source_url=url, facility=facility)
        return FinraDailyFile(
            as_of_date=as_of,
            facility=facility,
            provenance=FINRA_SHORT_VOLUME_PROVENANCE,
            source_url=url,
            rows=rows,
            status="available" if rows else "unavailable",
            message=None if rows else "The FINRA file parsed but contained no symbol rows.",
        )

    def get_latest_file(
        self,
        *,
        as_of: date | None = None,
        lookback_calendar_days: int = 10,
        facility: str = FINRA_REGSHO_FACILITY,
    ) -> FinraDailyFile:
        cursor = as_of or date.today()
        last_unavailable: FinraDailyFile | None = None
        for _ in range(max(lookback_calendar_days, 1)):
            daily = self.fetch_daily_file(cursor, facility=facility)
            if daily.status == "available":
                return daily
            last_unavailable = daily
            cursor -= timedelta(days=1)
        return last_unavailable or FinraDailyFile(
            as_of_date=as_of or date.today(),
            facility=facility,
            provenance=FINRA_SHORT_VOLUME_PROVENANCE,
            source_url=daily_file_url(as_of or date.today(), facility=facility),
            status="unavailable",
            message="No recent FINRA CNMS short-volume file was available.",
        )

    def get_latest_row(self, ticker: str, *, as_of: date | None = None) -> FinraShortVolumeRow | None:
        daily = self.get_latest_file(as_of=as_of)
        if daily.status != "available":
            return None
        return daily.row_for_symbol(ticker)

    def iter_available_files(
        self,
        start: date,
        end: date,
        *,
        facility: str = FINRA_REGSHO_FACILITY,
    ) -> Iterable[FinraDailyFile]:
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5:
                daily = self.fetch_daily_file(cursor, facility=facility)
                if daily.status == "available":
                    yield daily
            cursor += timedelta(days=1)

    def available_session_dates(
        self,
        start: date,
        end: date,
        *,
        facility: str = FINRA_REGSHO_FACILITY,
    ) -> tuple[date, ...]:
        return tuple(daily.as_of_date for daily in self.iter_available_files(start, end, facility=facility))

    def _read_daily_text(self, as_of: date, *, facility: str, url: str) -> str | None:
        now = time.monotonic()
        cache_key = f"{facility}:{as_of.isoformat()}"
        with _CACHE_LOCK:
            cached = _MEMORY_FILE_CACHE.get(cache_key)
            if cached and now - cached[0] <= self.cache_ttl_seconds:
                return cached[1]
        disk_path = self.cache_dir / f"{facility}shvol{as_of.strftime('%Y%m%d')}.txt"
        if disk_path.exists():
            text = disk_path.read_text(encoding="utf-8")
            with _CACHE_LOCK:
                _MEMORY_FILE_CACHE[cache_key] = (now, text)
            return text

        global _LAST_REQUEST_AT
        with _REQUEST_LOCK:
            with _CACHE_LOCK:
                cached = _MEMORY_FILE_CACHE.get(cache_key)
                if cached and time.monotonic() - cached[0] <= self.cache_ttl_seconds:
                    return cached[1]
            wait_seconds = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            try:
                raw = self._fetch(url)
            except HTTPError as exc:
                _LAST_REQUEST_AT = time.monotonic()
                if exc.code in {404, 403}:
                    with _CACHE_LOCK:
                        _MEMORY_FILE_CACHE[cache_key] = (time.monotonic(), None)
                    return None
                _log.warning("FINRA Reg SHO fetch failed for %s (%s).", url, exc.code)
                return None
            except (URLError, TimeoutError, OSError):
                _log.warning("FINRA Reg SHO fetch error for %s.", url, exc_info=True)
                return None
            _LAST_REQUEST_AT = time.monotonic()

        text = raw.decode("utf-8", errors="replace")
        try:
            ensure_parent(disk_path)
            disk_path.write_text(text, encoding="utf-8")
        except OSError:
            _log.warning("Could not persist FINRA Reg SHO cache to %s.", disk_path, exc_info=True)
        with _CACHE_LOCK:
            _MEMORY_FILE_CACHE[cache_key] = (time.monotonic(), text)
        return text

    def _fetch(self, url: str) -> bytes:
        if self._fetch_bytes is not None:
            return self._fetch_bytes(url)
        return _default_fetch_bytes(url, timeout_seconds=self.timeout_seconds)


def build_finra_short_volume_client() -> FinraShortVolumeClient:
    return FinraShortVolumeClient()


def reset_finra_short_volume_caches() -> None:
    with _CACHE_LOCK:
        _MEMORY_FILE_CACHE.clear()


__all__ = [
    "FinraDailyFile",
    "FinraShortVolumeClient",
    "FinraShortVolumeRow",
    "build_finra_short_volume_client",
    "daily_file_url",
    "parse_regsho_text",
    "reset_finra_short_volume_caches",
]
