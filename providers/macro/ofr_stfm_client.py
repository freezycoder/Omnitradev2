from __future__ import annotations

import csv
import gzip
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import ALFRED_BASE_URL, FRED_BASE_URL, FRED_PUBLIC_CSV_URL, settings
from config.stfm_funding_liquidity import (
    ALFRED_PRE_TRUNCATION_VINTAGE,
    ALFRED_REALTIME_END,
    ALFRED_REALTIME_START,
    ANFCI_INGEST_V1,
    DAILY_RELEASE_LAG_CALENDAR_DAYS,
    FROZEN_MNEMONICS,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_MIN_SERIES_SESSIONS_RECOMMENDED,
    HY_OAS_SERIES_ID,
    ICE_REDISTRIBUTION_NOTICE,
    IG_OAS_SERIES_ID,
    MIN_MMF_MONTHS_HARD,
    MIN_NFCI_WEEKS_HARD,
    MIN_STFM_SESSIONS_HARD,
    MIN_STFM_SESSIONS_RECOMMENDED,
    MMF_RELEASE_LAG_CALENDAR_DAYS,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_EFFR,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    NFCI_RELEASE_LAG_CALENDAR_DAYS,
    NFCI_SERIES_ID,
    OFR_STFM_BASE_URL,
    OFR_STFM_USER_AGENT,
    RORO_INGEST_V1,
    stfm_recipe_manifest,
)


_log = logging.getLogger(__name__)
RESEARCH_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class OfrPoint:
    observation_date: date
    release_date: date
    value: float | None
    mnemonic: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_date": self.observation_date.isoformat(),
            "release_date": self.release_date.isoformat(),
            "value": self.value,
            "mnemonic": self.mnemonic,
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
class NfciKeepObservation:
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
class StfmSeriesBundle:
    status: str
    source: str
    retrieved_at: str
    series: dict[str, tuple[OfrPoint, ...]] = field(default_factory=dict)
    hy_observations: tuple[HyKeepObservation, ...] = field(default_factory=tuple)
    nfci_observations: tuple[NfciKeepObservation, ...] = field(default_factory=tuple)
    null_counts: dict[str, int] = field(default_factory=dict)
    message: str | None = None
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE
    history_plan: dict[str, Any] = field(default_factory=dict)
    roro_ingest_v1: bool = RORO_INGEST_V1

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["series"] = {
            mnemonic: [row.to_dict() for row in rows] for mnemonic, rows in self.series.items()
        }
        payload["hy_observations"] = [row.to_dict() for row in self.hy_observations]
        payload["nfci_observations"] = [row.to_dict() for row in self.nfci_observations]
        payload["recipe"] = stfm_recipe_manifest()
        payload["frozen_mnemonics"] = list(FROZEN_MNEMONICS)
        return payload


class OfrStfmClient:
    """Research-only OFR STFM ingest for the frozen mnemonic set.

    KEEP HY OAS and NFCI are fetched as nested-kill comparators. RORO is not
    ingested. This client is not a live overlay.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        ofr_base_url: str = OFR_STFM_BASE_URL,
        fred_base_url: str = FRED_BASE_URL,
        alfred_base_url: str = ALFRED_BASE_URL,
        public_csv_url: str = FRED_PUBLIC_CSV_URL,
        timeout_seconds: int = RESEARCH_TIMEOUT_SECONDS,
        allow_public_csv: bool = True,
        include_keep_comparators: bool = True,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.fred_api_key).strip()
        self.ofr_base_url = ofr_base_url.rstrip("/")
        self.fred_base_url = fred_base_url.rstrip("/")
        self.alfred_base_url = alfred_base_url.rstrip("/")
        self.public_csv_url = public_csv_url
        self.timeout_seconds = timeout_seconds
        self.allow_public_csv = allow_public_csv
        self.include_keep_comparators = include_keep_comparators

    def fetch_bundle(self) -> StfmSeriesBundle:
        retrieved_at = datetime.now(UTC).isoformat()
        series: dict[str, tuple[OfrPoint, ...]] = {}
        null_counts: dict[str, int] = {}
        errors: list[str] = []
        ofr_source = "ofr_stfm"
        for mnemonic in FROZEN_MNEMONICS:
            try:
                rows = self.fetch_mnemonic(mnemonic)
            except Exception as exc:
                _log.warning("OFR STFM series %s was unavailable.", mnemonic, exc_info=True)
                errors.append(f"{mnemonic} unavailable ({exc.__class__.__name__})")
                continue
            series[mnemonic] = rows
            null_counts[mnemonic] = sum(row.value is None for row in rows)

        hy_observations: tuple[HyKeepObservation, ...] = ()
        nfci_observations: tuple[NfciKeepObservation, ...] = ()
        hy_source = "unavailable"
        nfci_source = "unavailable"
        hy_error: str | None = None
        ig_error: str | None = None
        nfci_error: str | None = None
        hy_count = 0
        ig_count = 0
        if self.include_keep_comparators:
            hy_points: dict[date, float] = {}
            ig_points: dict[date, float] = {}
            try:
                hy_points, hy_source = self._fetch_daily_series(HY_OAS_SERIES_ID)
            except Exception as exc:
                _log.warning("HY OAS series %s was unavailable.", HY_OAS_SERIES_ID, exc_info=True)
                hy_error = f"{HY_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"
            try:
                ig_points, _ig_source = self._fetch_daily_series(IG_OAS_SERIES_ID)
            except Exception as exc:
                _log.warning("IG OAS series %s was unavailable.", IG_OAS_SERIES_ID, exc_info=True)
                ig_error = f"{IG_OAS_SERIES_ID} unavailable ({exc.__class__.__name__})"
            hy_dates = sorted(set(hy_points) | set(ig_points))
            hy_observations = tuple(
                HyKeepObservation(as_of=as_of, hy_oas=hy_points.get(as_of), ig_oas=ig_points.get(as_of))
                for as_of in hy_dates
                if hy_points.get(as_of) is not None or ig_points.get(as_of) is not None
            )
            hy_count = sum(row.hy_oas is not None for row in hy_observations)
            ig_count = sum(row.ig_oas is not None for row in hy_observations)
            try:
                nfci_observations, nfci_source = self._fetch_nfci()
            except Exception as exc:
                _log.warning("NFCI series %s was unavailable.", NFCI_SERIES_ID, exc_info=True)
                nfci_error = f"{NFCI_SERIES_ID} unavailable ({exc.__class__.__name__})"

        dvp_count = _numeric_count(series.get(MNEMONIC_DVP_VOLUME, ()))
        gcf_count = _numeric_count(series.get(MNEMONIC_GCF_VOLUME, ()))
        sofr_count = _numeric_count(series.get(MNEMONIC_SOFR, ()))
        effr_count = _numeric_count(series.get(MNEMONIC_EFFR, ()))
        mmf_count = _numeric_count(series.get(MNEMONIC_MMF_TOTAL, ()))
        nfci_count = len(nfci_observations)
        daily_count = min(dvp_count, gcf_count, sofr_count, effr_count)
        keep_errors = [item for item in (hy_error, ig_error, nfci_error) if item]
        errors.extend(keep_errors)
        history_plan = {
            "ofr_source": ofr_source,
            "hy_source": hy_source,
            "nfci_source": nfci_source,
            "dvp_count": dvp_count,
            "gcf_count": gcf_count,
            "sofr_count": sofr_count,
            "effr_count": effr_count,
            "mmf_count": mmf_count,
            "hy_count": hy_count,
            "ig_count": ig_count,
            "nfci_count": nfci_count,
            "min_stfm_sessions_hard": MIN_STFM_SESSIONS_HARD,
            "min_stfm_sessions_recommended": MIN_STFM_SESSIONS_RECOMMENDED,
            "min_mmf_months_hard": MIN_MMF_MONTHS_HARD,
            "min_hy_sessions_hard": HY_MIN_SERIES_SESSIONS_HARD,
            "min_nfci_weeks_hard": MIN_NFCI_WEEKS_HARD,
            "meets_stfm_hard_minimum": daily_count >= MIN_STFM_SESSIONS_HARD,
            "meets_mmf_hard_minimum": mmf_count >= MIN_MMF_MONTHS_HARD,
            "meets_hy_hard_minimum": hy_count >= HY_MIN_SERIES_SESSIONS_HARD,
            "meets_nfci_hard_minimum": nfci_count >= MIN_NFCI_WEEKS_HARD,
            "data_blocked": daily_count < MIN_STFM_SESSIONS_HARD,
            "hy_keep_unavailable": hy_count < HY_MIN_SERIES_SESSIONS_HARD,
            "nfci_keep_unavailable": nfci_count < MIN_NFCI_WEEKS_HARD,
            "roro_ingest_v1": RORO_INGEST_V1,
            "anfci_ingest_v1": ANFCI_INGEST_V1,
            "null_counts": null_counts,
            "frozen_mnemonics": list(FROZEN_MNEMONICS),
        }
        missing_frozen = [mnemonic for mnemonic in FROZEN_MNEMONICS if mnemonic not in series]
        if missing_frozen or daily_count == 0:
            status = "unavailable"
            message = "; ".join(errors) if errors else "OFR STFM observations were empty."
        elif daily_count < MIN_STFM_SESSIONS_HARD or mmf_count < MIN_MMF_MONTHS_HARD:
            status = "data_blocked"
            message = (
                f"OFR STFM returned {daily_count} aligned daily observations and "
                f"{mmf_count} MMF months; {MIN_STFM_SESSIONS_HARD} daily sessions and "
                f"{MIN_MMF_MONTHS_HARD} MMF months are required. FAIL data-blocked."
            )
        else:
            status = "available"
            message = None
            if daily_count < MIN_STFM_SESSIONS_RECOMMENDED:
                message = (
                    f"OFR STFM has {daily_count} daily observations, below the recommended "
                    f"{MIN_STFM_SESSIONS_RECOMMENDED}-session budget, but the hard minimum "
                    "for the frozen recipe is met."
                )
            if hy_count < HY_MIN_SERIES_SESSIONS_HARD or nfci_count < MIN_NFCI_WEEKS_HARD:
                status = "partial"
                keep_note = (
                    f"KEEP HY OAS has {hy_count} sessions (need {HY_MIN_SERIES_SESSIONS_HARD}) "
                    f"and KEEP NFCI has {nfci_count} weeks (need {MIN_NFCI_WEEKS_HARD}). "
                    "Nested kill-switch vs HY+NFCI cannot be scored until both KEEP series "
                    "meet their hard minima."
                )
                message = f"{message} {keep_note}".strip() if message else keep_note
        return StfmSeriesBundle(
            status=status,
            source=_combined_source(ofr_source, hy_source, nfci_source),
            retrieved_at=retrieved_at,
            series=series,
            hy_observations=hy_observations,
            nfci_observations=nfci_observations,
            null_counts=null_counts,
            message=message,
            history_plan=history_plan,
        )

    def fetch_mnemonic(self, mnemonic: str) -> tuple[OfrPoint, ...]:
        if mnemonic not in FROZEN_MNEMONICS:
            raise ValueError(f"{mnemonic} is not in the frozen STFM mnemonic set.")
        payload = self._get_json(
            f"{self.ofr_base_url}/series/timeseries?{urlencode({'mnemonic': mnemonic})}"
        )
        lag = (
            MMF_RELEASE_LAG_CALENDAR_DAYS
            if mnemonic == MNEMONIC_MMF_TOTAL
            else DAILY_RELEASE_LAG_CALENDAR_DAYS
        )
        return _points_from_timeseries(payload, mnemonic=mnemonic, lag_days=lag)

    def _fetch_nfci(self) -> tuple[tuple[NfciKeepObservation, ...], str]:
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

    def _fred_nfci_initial_release(self) -> tuple[NfciKeepObservation, ...]:
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
    ) -> tuple[NfciKeepObservation, ...]:
        return tuple(
            NfciKeepObservation(
                observation_week_end=week_end,
                release_date=week_end + timedelta(days=NFCI_RELEASE_LAG_CALENDAR_DAYS),
                nfci=value,
                release_source=release_source,
            )
            for week_end, value in sorted(points.items())
        )

    def _get_json(self, url: str) -> Any:
        raw = self._get_bytes(url, accept="application/json")
        return json.loads(raw.decode("utf-8"))

    def _get_text(self, url: str) -> str:
        return self._get_bytes(url, accept="text/csv").decode("utf-8")

    def _get_bytes(self, url: str, *, accept: str) -> bytes:
        request = Request(
            url,
            headers={
                "Accept": accept,
                "User-Agent": OFR_STFM_USER_AGENT,
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read()
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        return raw


def build_ofr_stfm_client() -> OfrStfmClient:
    return OfrStfmClient()


def _points_from_timeseries(
    payload: Any,
    *,
    mnemonic: str,
    lag_days: int,
) -> tuple[OfrPoint, ...]:
    rows = _extract_pairs(payload)
    points: list[OfrPoint] = []
    for raw_date, raw_value in rows:
        observation = _parse_date(raw_date)
        if observation is None:
            continue
        value = _parse_float(raw_value)
        points.append(
            OfrPoint(
                observation_date=observation,
                release_date=observation + timedelta(days=lag_days),
                value=value,
                mnemonic=mnemonic,
            )
        )
    points.sort(key=lambda row: (row.release_date, row.observation_date))
    return tuple(points)


def _extract_pairs(payload: Any) -> list[list[Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, (list, tuple)) and len(item) >= 2]
    if isinstance(payload, dict):
        inner = payload.get("timeseries") or payload.get("data") or payload
        if isinstance(inner, dict) and "aggregation" in inner:
            inner = inner["aggregation"]
        if isinstance(inner, list):
            return [item for item in inner if isinstance(item, (list, tuple)) and len(item) >= 2]
    return []


def _numeric_count(rows: tuple[OfrPoint, ...]) -> int:
    return sum(row.value is not None for row in rows)


def _nfci_from_vintage_payload(payload: dict[str, Any]) -> tuple[NfciKeepObservation, ...]:
    first_release: dict[date, tuple[date, float, str]] = {}
    for item in payload.get("observations", []):
        parsed = _parse_observation(item.get("date"), item.get("value"))
        if parsed is None:
            continue
        week_end, value = parsed
        realtime = _parse_date(item.get("realtime_start"))
        if realtime is None:
            release = week_end + timedelta(days=NFCI_RELEASE_LAG_CALENDAR_DAYS)
            source = "fred_api_release_lag"
        else:
            release = realtime
            source = "alfred_initial_release"
        current = first_release.get(week_end)
        if current is None or release < current[0]:
            first_release[week_end] = (release, value, source)
    return tuple(
        NfciKeepObservation(
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
    observation = _parse_date(raw_date)
    value = _parse_float(raw_value)
    if observation is None or value is None:
        return None
    return observation, value


def _parse_date(raw_date: Any) -> date | None:
    if raw_date in (None, "", "."):
        return None
    try:
        return date.fromisoformat(str(raw_date)[:10])
    except (TypeError, ValueError):
        return None


def _parse_float(raw_value: Any) -> float | None:
    if raw_value in (None, "", "."):
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value != value:
        return None
    return value


def _combined_source(ofr_source: str, hy_source: str, nfci_source: str) -> str:
    parts = [ofr_source]
    for source in (hy_source, nfci_source):
        if source not in {"unavailable", ""} and source not in parts:
            parts.append(source)
    return "+".join(parts)


__all__ = [
    "HyKeepObservation",
    "NfciKeepObservation",
    "OfrPoint",
    "OfrStfmClient",
    "StfmSeriesBundle",
    "build_ofr_stfm_client",
]
