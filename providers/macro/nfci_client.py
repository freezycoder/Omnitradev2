from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.nfci_regime import (
    ALFRED_PRE_TRUNCATION_VINTAGE,
    ALFRED_REALTIME_END,
    ALFRED_REALTIME_START,
    ANFCI_INGEST_V1,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_MIN_SERIES_SESSIONS_RECOMMENDED,
    HY_OAS_SERIES_ID,
    ICE_REDISTRIBUTION_NOTICE,
    IG_OAS_SERIES_ID,
    MIN_NFCI_WEEKS_HARD,
    MIN_NFCI_WEEKS_RECOMMENDED,
    NFCI_SERIES_ID,
    RELEASE_LAG_CALENDAR_DAYS,
    nfci_recipe_manifest,
)
from config.settings import (
    ALFRED_BASE_URL,
    FRED_BASE_URL,
    FRED_PUBLIC_CSV_URL,
    settings,
)


_log = logging.getLogger(__name__)
RESEARCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class NfciObservation:
    observation_week_end: date
    release_date: date
    nfci: float
    release_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_week_end": self.observation_week_end.isoformat(),
            "release_date": self.release_date.isoformat(),
            "nfci": self.nfci,
            "release_source": self.release_source,
        }


@dataclass(frozen=True)
class HyKeepObservation:
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
class NfciSeriesBundle:
    status: str
    source: str
    retrieved_at: str
    observations: tuple[NfciObservation, ...] = field(default_factory=tuple)
    hy_observations: tuple[HyKeepObservation, ...] = field(default_factory=tuple)
    nfci_count: int = 0
    hy_count: int = 0
    ig_count: int = 0
    first_release_date: date | None = None
    last_release_date: date | None = None
    message: str | None = None
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE
    history_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observations"] = [row.to_dict() for row in self.observations]
        payload["hy_observations"] = [row.to_dict() for row in self.hy_observations]
        payload["first_release_date"] = (
            self.first_release_date.isoformat() if self.first_release_date else None
        )
        payload["last_release_date"] = (
            self.last_release_date.isoformat() if self.last_release_date else None
        )
        payload["observation_count"] = len(self.observations)
        payload["recipe"] = nfci_recipe_manifest()
        payload["anfci_ingest_v1"] = ANFCI_INGEST_V1
        return payload


class NfciClient:
    """Research-only FRED/ALFRED ingest for weekly NFCI plus KEEP HY OAS.

    Joins must use release_date, not the Friday week-end label. This client is
    not a live overlay and does not ingest ANFCI in v1.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        fred_base_url: str = FRED_BASE_URL,
        alfred_base_url: str = ALFRED_BASE_URL,
        public_csv_url: str = FRED_PUBLIC_CSV_URL,
        timeout_seconds: int = RESEARCH_TIMEOUT_SECONDS,
        allow_public_csv: bool = True,
        include_hy_keep: bool = True,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.fred_api_key).strip()
        self.fred_base_url = fred_base_url.rstrip("/")
        self.alfred_base_url = alfred_base_url.rstrip("/")
        self.public_csv_url = public_csv_url
        self.timeout_seconds = timeout_seconds
        self.allow_public_csv = allow_public_csv
        self.include_hy_keep = include_hy_keep

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self.allow_public_csv

    def fetch_bundle(self) -> NfciSeriesBundle:
        retrieved_at = datetime.now(UTC).isoformat()
        nfci_error: str | None = None
        hy_error: str | None = None
        ig_error: str | None = None
        nfci_source = "unavailable"
        hy_source = "unavailable"
        ig_source = "unavailable"
        try:
            nfci_rows, nfci_source = self._fetch_nfci()
        except Exception as exc:
            _log.warning("NFCI series %s was unavailable.", NFCI_SERIES_ID, exc_info=True)
            nfci_rows = ()
            nfci_error = f"{NFCI_SERIES_ID} unavailable ({exc.__class__.__name__})"

        hy_points: dict[date, float] = {}
        ig_points: dict[date, float] = {}
        if self.include_hy_keep:
            try:
                hy_points, hy_source = self._fetch_daily_series(HY_OAS_SERIES_ID)
            except Exception as exc:
                _log.warning("HY OAS series %s was unavailable.", HY_OAS_SERIES_ID, exc_info=True)
                hy_error = f"{HY_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"
            try:
                ig_points, ig_source = self._fetch_daily_series(IG_OAS_SERIES_ID)
            except Exception as exc:
                _log.warning("IG OAS series %s was unavailable.", IG_OAS_SERIES_ID, exc_info=True)
                ig_error = f"{IG_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"

        hy_dates = sorted(set(hy_points) | set(ig_points))
        hy_observations = tuple(
            HyKeepObservation(
                as_of=as_of,
                hy_oas=hy_points.get(as_of),
                ig_oas=ig_points.get(as_of),
            )
            for as_of in hy_dates
            if hy_points.get(as_of) is not None or ig_points.get(as_of) is not None
        )
        nfci_count = len(nfci_rows)
        hy_count = sum(row.hy_oas is not None for row in hy_observations)
        ig_count = sum(row.ig_oas is not None for row in hy_observations)
        errors = [item for item in (nfci_error, hy_error, ig_error) if item]
        history_plan = {
            "nfci_source": nfci_source,
            "hy_source": hy_source,
            "ig_source": ig_source,
            "nfci_count": nfci_count,
            "hy_count": hy_count,
            "ig_count": ig_count,
            "min_nfci_weeks_hard": MIN_NFCI_WEEKS_HARD,
            "min_nfci_weeks_recommended": MIN_NFCI_WEEKS_RECOMMENDED,
            "min_hy_sessions_hard": HY_MIN_SERIES_SESSIONS_HARD,
            "min_hy_sessions_recommended": HY_MIN_SERIES_SESSIONS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
            "release_lag_calendar_days": RELEASE_LAG_CALENDAR_DAYS,
            "meets_nfci_hard_minimum": nfci_count >= MIN_NFCI_WEEKS_HARD,
            "meets_hy_hard_minimum": hy_count >= HY_MIN_SERIES_SESSIONS_HARD,
            "data_blocked": nfci_count < MIN_NFCI_WEEKS_HARD,
            "hy_keep_unavailable": hy_count < HY_MIN_SERIES_SESSIONS_HARD,
            "anfci_ingest_v1": ANFCI_INGEST_V1,
        }
        if nfci_count == 0:
            status = "unavailable"
            message = "; ".join(errors) if errors else "NFCI observations were empty."
        elif nfci_count < MIN_NFCI_WEEKS_HARD:
            status = "data_blocked"
            message = (
                f"{NFCI_SERIES_ID} returned {nfci_count} weekly observations; "
                f"{MIN_NFCI_WEEKS_HARD} are required for the frozen recipe. "
                "FAIL data-blocked."
            )
        elif hy_count < HY_MIN_SERIES_SESSIONS_HARD:
            status = "partial"
            message = (
                f"{NFCI_SERIES_ID} ingested from {nfci_source} with {nfci_count} weeks, "
                f"but KEEP HY OAS has {hy_count} sessions "
                f"(need {HY_MIN_SERIES_SESSIONS_HARD}). Nested kill-switch vs HY OAS "
                "cannot be scored until the KEEP series meets the hard minimum."
            )
        else:
            status = "available"
            message = None
            if nfci_count < MIN_NFCI_WEEKS_RECOMMENDED:
                message = (
                    f"{NFCI_SERIES_ID} has {nfci_count} weeks, below the recommended "
                    f"{MIN_NFCI_WEEKS_RECOMMENDED}-week budget, but the hard minimum "
                    "for the frozen recipe is met."
                )
        return NfciSeriesBundle(
            status=status,
            source=_combined_source(nfci_source, hy_source),
            retrieved_at=retrieved_at,
            observations=nfci_rows,
            hy_observations=hy_observations,
            nfci_count=nfci_count,
            hy_count=hy_count,
            ig_count=ig_count,
            first_release_date=nfci_rows[0].release_date if nfci_rows else None,
            last_release_date=nfci_rows[-1].release_date if nfci_rows else None,
            message=message,
            history_plan=history_plan,
        )

    def _fetch_nfci(self) -> tuple[tuple[NfciObservation, ...], str]:
        if self.api_key:
            vintage_rows = self._fred_nfci_initial_release()
            if vintage_rows:
                return vintage_rows, "fred_alfred_initial_release"
            current_rows = self._nfci_from_points(
                self._fred_observations(NFCI_SERIES_ID),
                release_source="fred_api_release_lag",
            )
            if current_rows:
                return current_rows, "fred_api_release_lag"
        if self.allow_public_csv:
            csv_rows = self._nfci_from_points(
                self._public_csv_observations(NFCI_SERIES_ID),
                release_source="fred_public_csv_release_lag",
            )
            if csv_rows:
                return csv_rows, "fred_public_csv_release_lag"
        raise RuntimeError(f"{NFCI_SERIES_ID} returned no observations")

    def _fetch_daily_series(self, series_id: str) -> tuple[dict[date, float], str]:
        fred_points: dict[date, float] = {}
        source = "unavailable"
        if self.api_key:
            fred_points = self._fred_observations(series_id)
            source = "fred_api"
            if len(fred_points) < HY_MIN_SERIES_SESSIONS_RECOMMENDED:
                alfred_points = self._alfred_observations(series_id)
                if alfred_points:
                    merged = dict(alfred_points)
                    merged.update(fred_points)
                    if len(merged) > len(fred_points):
                        return merged, "fred_alfred_merged"
                    if len(alfred_points) > len(fred_points):
                        return alfred_points, f"alfred_vintage_{ALFRED_PRE_TRUNCATION_VINTAGE}"
        if len(fred_points) >= HY_MIN_SERIES_SESSIONS_HARD:
            return fred_points, source
        if self.allow_public_csv:
            csv_points = self._public_csv_observations(series_id)
            if len(csv_points) > len(fred_points):
                return csv_points, "fred_public_csv"
        if fred_points:
            return fred_points, source
        raise RuntimeError(f"{series_id} returned no observations")

    def _fred_nfci_initial_release(self) -> tuple[NfciObservation, ...]:
        query = urlencode(
            {
                "series_id": NFCI_SERIES_ID,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "asc",
                "realtime_start": ALFRED_REALTIME_START,
                "realtime_end": ALFRED_REALTIME_END,
            }
        )
        try:
            payload = self._get_json(f"{self.fred_base_url}/series/observations?{query}")
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError):
            _log.warning("ALFRED-style NFCI vintage window failed.", exc_info=True)
            return ()
        return _nfci_from_vintage_payload(payload)

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
            _log.warning(
                "ALFRED vintage %s for %s failed.",
                ALFRED_PRE_TRUNCATION_VINTAGE,
                series_id,
                exc_info=True,
            )
            return {}
        return _observations_from_payload(payload)

    def _public_csv_observations(self, series_id: str) -> dict[date, float]:
        query = urlencode({"id": series_id})
        text = self._get_text(f"{self.public_csv_url}?{query}")
        return _observations_from_csv(text, series_id)

    def _nfci_from_points(
        self,
        points: dict[date, float],
        *,
        release_source: str,
    ) -> tuple[NfciObservation, ...]:
        rows = [
            NfciObservation(
                observation_week_end=week_end,
                release_date=_fallback_release_date(week_end),
                nfci=value,
                release_source=release_source,
            )
            for week_end, value in sorted(points.items())
        ]
        return tuple(rows)

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


def build_nfci_client() -> NfciClient:
    return NfciClient()


def _nfci_from_vintage_payload(payload: dict[str, Any]) -> tuple[NfciObservation, ...]:
    first_release: dict[date, tuple[date, float, str]] = {}
    for item in payload.get("observations", []):
        parsed = _parse_observation(item.get("date"), item.get("value"))
        if parsed is None:
            continue
        week_end, value = parsed
        realtime = _parse_date(item.get("realtime_start"))
        if realtime is None:
            release = _fallback_release_date(week_end)
            source = "fred_api_release_lag"
        else:
            release = realtime
            source = "alfred_initial_release"
        current = first_release.get(week_end)
        if current is None or release < current[0]:
            first_release[week_end] = (release, value, source)
    return tuple(
        NfciObservation(
            observation_week_end=week_end,
            release_date=release,
            nfci=value,
            release_source=source,
        )
        for week_end, (release, value, source) in sorted(first_release.items())
    )


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


def _parse_date(raw_date: Any) -> date | None:
    if raw_date in (None, "", "."):
        return None
    try:
        return date.fromisoformat(str(raw_date)[:10])
    except (TypeError, ValueError):
        return None


def _fallback_release_date(week_end: date) -> date:
    return week_end + timedelta(days=RELEASE_LAG_CALENDAR_DAYS)


def _combined_source(nfci_source: str, hy_source: str) -> str:
    if hy_source in {"unavailable", ""}:
        return nfci_source
    if nfci_source == hy_source:
        return nfci_source
    return f"{nfci_source}+{hy_source}"


__all__ = [
    "HyKeepObservation",
    "NfciClient",
    "NfciObservation",
    "NfciSeriesBundle",
    "build_nfci_client",
]
