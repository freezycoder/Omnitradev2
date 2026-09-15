from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.credit_regime import (
    ALFRED_PRE_TRUNCATION_VINTAGE,
    HY_OAS_SERIES_ID,
    HY_OAS_SERIES_LABEL,
    ICE_REDISTRIBUTION_NOTICE,
    IG_OAS_SERIES_ID,
    IG_OAS_SERIES_LABEL,
    MIN_SERIES_SESSIONS_HARD,
    MIN_SERIES_SESSIONS_RECOMMENDED,
    credit_recipe_manifest,
)
from config.settings import (
    ALFRED_BASE_URL,
    FRED_BASE_URL,
    FRED_PUBLIC_CSV_URL,
    FRED_TIMEOUT_SECONDS,
    settings,
)


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreditSeriesObservation:
    as_of: date
    hy_oas: float | None
    ig_oas: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "hy_oas": self.hy_oas,
            "ig_oas": self.ig_oas,
        }


@dataclass(frozen=True)
class CreditSeriesBundle:
    status: str
    source: str
    retrieved_at: str
    observations: tuple[CreditSeriesObservation, ...] = field(default_factory=tuple)
    hy_count: int = 0
    ig_count: int = 0
    first_date: date | None = None
    last_date: date | None = None
    message: str | None = None
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE
    history_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observations"] = [row.to_dict() for row in self.observations]
        payload["first_date"] = self.first_date.isoformat() if self.first_date else None
        payload["last_date"] = self.last_date.isoformat() if self.last_date else None
        payload["observation_count"] = len(self.observations)
        payload["recipe"] = credit_recipe_manifest()
        return payload


class CreditOasClient:
    """Research-only FRED/ALFRED ingest for HY and IG OAS. Not a live overlay."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        fred_base_url: str = FRED_BASE_URL,
        alfred_base_url: str = ALFRED_BASE_URL,
        public_csv_url: str = FRED_PUBLIC_CSV_URL,
        timeout_seconds: int = FRED_TIMEOUT_SECONDS,
        allow_public_csv: bool = True,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.fred_api_key).strip()
        self.fred_base_url = fred_base_url.rstrip("/")
        self.alfred_base_url = alfred_base_url.rstrip("/")
        self.public_csv_url = public_csv_url
        self.timeout_seconds = timeout_seconds
        self.allow_public_csv = allow_public_csv

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self.allow_public_csv

    def fetch_bundle(self) -> CreditSeriesBundle:
        retrieved_at = datetime.now(UTC).isoformat()
        hy_source = "unavailable"
        ig_source = "unavailable"
        hy_error: str | None = None
        ig_error: str | None = None
        try:
            hy_points, hy_source = self._fetch_series(HY_OAS_SERIES_ID)
        except Exception as exc:
            _log.warning("HY OAS series %s was unavailable.", HY_OAS_SERIES_ID, exc_info=True)
            hy_points = {}
            hy_error = f"{HY_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"
        try:
            ig_points, ig_source = self._fetch_series(IG_OAS_SERIES_ID)
        except Exception as exc:
            _log.warning("IG OAS series %s was unavailable.", IG_OAS_SERIES_ID, exc_info=True)
            ig_points = {}
            ig_error = f"{IG_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"

        dates = sorted(set(hy_points) | set(ig_points))
        observations = tuple(
            CreditSeriesObservation(
                as_of=as_of,
                hy_oas=hy_points.get(as_of),
                ig_oas=ig_points.get(as_of),
            )
            for as_of in dates
            if hy_points.get(as_of) is not None or ig_points.get(as_of) is not None
        )
        hy_count = sum(row.hy_oas is not None for row in observations)
        ig_count = sum(row.ig_oas is not None for row in observations)
        source = _combined_source(hy_source, ig_source)
        errors = [item for item in (hy_error, ig_error) if item]
        history_plan = {
            "hy_source": hy_source,
            "ig_source": ig_source,
            "hy_count": hy_count,
            "ig_count": ig_count,
            "min_sessions_hard": MIN_SERIES_SESSIONS_HARD,
            "min_sessions_recommended": MIN_SERIES_SESSIONS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
            "meets_hard_minimum": hy_count >= MIN_SERIES_SESSIONS_HARD,
            "meets_recommended_minimum": hy_count >= MIN_SERIES_SESSIONS_RECOMMENDED,
            "data_blocked": hy_count < MIN_SERIES_SESSIONS_HARD,
            "march_2020_in_window": bool(observations)
            and observations[0].as_of <= date(2020, 3, 31)
            and (observations[-1].as_of >= date(2020, 3, 1)),
        }
        if hy_count == 0:
            status = "unavailable"
            message = "; ".join(errors) if errors else "HY OAS observations were empty."
        elif hy_count < MIN_SERIES_SESSIONS_HARD:
            status = "data_blocked"
            message = (
                f"{HY_OAS_SERIES_ID} returned {hy_count} observations; "
                f"{MIN_SERIES_SESSIONS_HARD} are required for the frozen recipe. "
                "ALFRED vintages and the public FRED CSV were insufficient. FAIL data-blocked."
            )
        elif not ig_count or errors:
            status = "partial"
            message = (
                f"{HY_OAS_SERIES_LABEL} ingested from {hy_source}. "
                + ("; ".join(errors) if errors else f"{IG_OAS_SERIES_ID} coverage is incomplete.")
            )
        else:
            status = "available"
            message = None
            if hy_count < MIN_SERIES_SESSIONS_RECOMMENDED:
                message = (
                    f"{HY_OAS_SERIES_ID} has {hy_count} observations, below the "
                    f"recommended {MIN_SERIES_SESSIONS_RECOMMENDED}-session budget, "
                    "but the hard minimum for the frozen recipe is met."
                )
        return CreditSeriesBundle(
            status=status,
            source=source,
            retrieved_at=retrieved_at,
            observations=observations,
            hy_count=hy_count,
            ig_count=ig_count,
            first_date=observations[0].as_of if observations else None,
            last_date=observations[-1].as_of if observations else None,
            message=message,
            history_plan=history_plan,
        )

    def _fetch_series(self, series_id: str) -> tuple[dict[date, float], str]:
        fred_points: dict[date, float] = {}
        source = "unavailable"
        if self.api_key:
            fred_points = self._fred_observations(series_id)
            source = "fred_api"
            if len(fred_points) < MIN_SERIES_SESSIONS_RECOMMENDED:
                alfred_points = self._alfred_observations(series_id)
                if alfred_points:
                    merged = dict(alfred_points)
                    merged.update(fred_points)
                    if len(merged) > len(fred_points):
                        return merged, "fred_alfred_merged"
                    if len(alfred_points) > len(fred_points):
                        return alfred_points, f"alfred_vintage_{ALFRED_PRE_TRUNCATION_VINTAGE}"
        if len(fred_points) >= MIN_SERIES_SESSIONS_HARD:
            return fred_points, source
        if self.allow_public_csv:
            csv_points = self._public_csv_observations(series_id)
            if len(csv_points) > len(fred_points):
                return csv_points, "fred_public_csv"
        if fred_points:
            return fred_points, source
        raise RuntimeError(f"{series_id} returned no observations")

    def _fred_observations(self, series_id: str) -> dict[date, float]:
        query = urlencode(
            {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "asc",
            }
        )
        payload = self._get_json(f"{self.fred_base_url}/series/observations?{query}")
        return _observations_from_payload(payload)

    def _alfred_observations(self, series_id: str) -> dict[date, float]:
        query = urlencode(
            {
                "series_id": series_id,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "asc",
                "vintage_dates": ALFRED_PRE_TRUNCATION_VINTAGE,
            }
        )
        try:
            payload = self._get_json(f"{self.alfred_base_url}/series/observations?{query}")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
            _log.warning("ALFRED vintage %s for %s failed.", ALFRED_PRE_TRUNCATION_VINTAGE, series_id, exc_info=True)
            return {}
        return _observations_from_payload(payload)

    def _public_csv_observations(self, series_id: str) -> dict[date, float]:
        query = urlencode({"id": series_id})
        text = self._get_text(f"{self.public_csv_url}?{query}")
        return _observations_from_csv(text, series_id)

    def _get_json(self, url: str) -> dict[str, Any]:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "OmniTrade/1.0"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_text(self, url: str) -> str:
        request = Request(
            url,
            headers={"Accept": "text/csv", "User-Agent": "OmniTrade/1.0"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return response.read().decode("utf-8")


def build_credit_oas_client() -> CreditOasClient:
    return CreditOasClient()


def _observations_from_payload(payload: dict[str, Any]) -> dict[date, float]:
    points: dict[date, float] = {}
    for item in payload.get("observations", []):
        parsed = _parse_observation(item.get("date"), item.get("value"))
        if parsed is not None:
            as_of, value = parsed
            points[as_of] = value
    return points


def _observations_from_csv(text: str, series_id: str) -> dict[date, float]:
    reader = csv.DictReader(io.StringIO(text))
    points: dict[date, float] = {}
    for row in reader:
        raw_date = row.get("observation_date") or row.get("DATE")
        raw_value = row.get(series_id) or row.get("VALUE")
        parsed = _parse_observation(raw_date, raw_value)
        if parsed is not None:
            as_of, value = parsed
            points[as_of] = value
    return points


def _parse_observation(raw_date: Any, raw_value: Any) -> tuple[date, float] | None:
    if raw_date is None or raw_value in (None, "", "."):
        return None
    try:
        as_of = date.fromisoformat(str(raw_date)[:10])
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return as_of, value


def _combined_source(hy_source: str, ig_source: str) -> str:
    if hy_source == ig_source:
        return hy_source
    if hy_source == "unavailable":
        return ig_source
    if ig_source == "unavailable":
        return hy_source
    return f"{hy_source}+{ig_source}"


__all__ = [
    "CreditOasClient",
    "CreditSeriesBundle",
    "CreditSeriesObservation",
    "build_credit_oas_client",
]
