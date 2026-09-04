from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from threading import RLock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import (
    FRED_BASE_URL,
    FRED_CACHE_TTL_SECONDS,
    FRED_TIMEOUT_SECONDS,
    settings,
)


_log = logging.getLogger(__name__)
_CACHE_LOCK = RLock()
_FETCH_LOCK = RLock()
_SNAPSHOT_CACHE: tuple[float, "FredMacroBundle"] | None = None

FRED_SERIES = {
    "yield_curve_10y_2y": {
        "series_id": "T10Y2Y",
        "label": "10Y–2Y Treasury spread",
        "unit": "percentage points",
    },
    "high_yield_spread": {
        "series_id": "BAMLH0A0HYM2",
        "label": "US high-yield option-adjusted spread",
        "unit": "percentage points",
    },
    "financial_conditions": {
        "series_id": "NFCI",
        "label": "Chicago Fed National Financial Conditions Index",
        "unit": "index",
    },
    "fed_funds": {
        "series_id": "DFF",
        "label": "Effective federal funds rate",
        "unit": "percent",
    },
}


@dataclass(frozen=True)
class FredSeriesSnapshot:
    key: str
    series_id: str
    label: str
    unit: str
    latest_value: float
    latest_date: str
    prior_value: float | None
    prior_date: str | None
    change: float | None


@dataclass(frozen=True)
class FredMacroBundle:
    status: str
    retrieved_at: str
    series: dict[str, FredSeriesSnapshot] = field(default_factory=dict)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FredClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = FRED_BASE_URL,
        timeout_seconds: int = FRED_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _get_series(self, key: str, metadata: dict[str, str]) -> FredSeriesSnapshot | None:
        observation_start = (date.today() - timedelta(days=180)).isoformat()
        query = urlencode(
            {
                "series_id": metadata["series_id"],
                "api_key": self.api_key,
                "file_type": "json",
                "observation_start": observation_start,
                "sort_order": "asc",
            }
        )
        request = Request(
            f"{self.base_url}/series/observations?{query}",
            headers={"Accept": "application/json", "User-Agent": "OmniTrade/1.0"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        observations: list[tuple[str, float]] = []
        for item in payload.get("observations", []):
            try:
                observations.append((str(item["date"]), float(item["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        if not observations:
            return None

        latest_date, latest_value = observations[-1]
        target = date.fromisoformat(latest_date) - timedelta(days=90)
        prior_candidates = [
            observation
            for observation in observations[:-1]
            if date.fromisoformat(observation[0]) <= target
        ]
        prior_date: str | None = None
        prior_value: float | None = None
        if prior_candidates:
            prior_date, prior_value = prior_candidates[-1]
        elif len(observations) >= 2:
            prior_date, prior_value = observations[0]
        change = latest_value - prior_value if prior_value is not None else None
        return FredSeriesSnapshot(
            key=key,
            series_id=metadata["series_id"],
            label=metadata["label"],
            unit=metadata["unit"],
            latest_value=latest_value,
            latest_date=latest_date,
            prior_value=prior_value,
            prior_date=prior_date,
            change=change,
        )

    def get_macro_bundle(self) -> FredMacroBundle:
        global _SNAPSHOT_CACHE
        now_monotonic = time.monotonic()
        with _CACHE_LOCK:
            if _SNAPSHOT_CACHE and now_monotonic - _SNAPSHOT_CACHE[0] <= FRED_CACHE_TTL_SECONDS:
                return _SNAPSHOT_CACHE[1]

        with _FETCH_LOCK:
            with _CACHE_LOCK:
                if _SNAPSHOT_CACHE and time.monotonic() - _SNAPSHOT_CACHE[0] <= FRED_CACHE_TTL_SECONDS:
                    return _SNAPSHOT_CACHE[1]

            retrieved_at = datetime.now(UTC).isoformat()
            if not self.enabled:
                bundle = FredMacroBundle(
                    status="unavailable",
                    retrieved_at=retrieved_at,
                    message="FRED macro context is disabled because FRED_API_KEY is not configured.",
                )
                with _CACHE_LOCK:
                    _SNAPSHOT_CACHE = (time.monotonic(), bundle)
                return bundle

            series: dict[str, FredSeriesSnapshot] = {}
            errors: list[str] = []
            for key, metadata in FRED_SERIES.items():
                try:
                    snapshot = self._get_series(key, metadata)
                except HTTPError as exc:
                    errors.append(f"{metadata['series_id']} HTTP {exc.code}")
                    continue
                except (URLError, TimeoutError, json.JSONDecodeError, ValueError):
                    _log.warning("FRED series %s was unavailable.", metadata["series_id"], exc_info=True)
                    errors.append(f"{metadata['series_id']} unavailable")
                    continue
                if snapshot is not None:
                    series[key] = snapshot

            if len(series) == len(FRED_SERIES):
                status = "available"
                message = None
            elif series:
                status = "partial"
                message = f"FRED macro context is partial: {', '.join(errors)}."
            else:
                status = "unavailable"
                message = "FRED macro context is unavailable right now."
            bundle = FredMacroBundle(
                status=status,
                retrieved_at=retrieved_at,
                series=series,
                message=message,
            )
            with _CACHE_LOCK:
                _SNAPSHOT_CACHE = (time.monotonic(), bundle)
            return bundle


def build_fred_client() -> FredClient:
    return FredClient(api_key=settings.fred_api_key)


def fred_macro_bundle_from_dict(payload: dict[str, Any] | None) -> FredMacroBundle | None:
    if not payload:
        return None
    series = {
        str(key): FredSeriesSnapshot(**value)
        for key, value in payload.get("series", {}).items()
        if isinstance(value, dict)
    }
    return FredMacroBundle(
        status=str(payload.get("status") or "unavailable"),
        retrieved_at=str(payload.get("retrieved_at") or datetime.now(UTC).isoformat()),
        series=series,
        message=str(payload["message"]) if payload.get("message") else None,
    )


__all__ = [
    "FRED_SERIES",
    "FredClient",
    "FredMacroBundle",
    "FredSeriesSnapshot",
    "build_fred_client",
    "fred_macro_bundle_from_dict",
]
