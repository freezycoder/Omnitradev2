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

from config.kcroro_regime import (
    ALFRED_PRE_TRUNCATION_VINTAGE,
    ALFRED_REALTIME_END,
    ALFRED_REALTIME_START,
    HY_MIN_SERIES_SESSIONS_HARD,
    HY_MIN_SERIES_SESSIONS_RECOMMENDED,
    HY_OAS_SERIES_ID,
    ICE_REDISTRIBUTION_NOTICE,
    IG_OAS_SERIES_ID,
    KCRORO_CITATION,
    KCRORO_EQUITY_SERIES_ID,
    KCRORO_FXGOLD_SERIES_ID,
    KCRORO_LIQUIDITY_SERIES_ID,
    KCRORO_SERIES_ID,
    KCRORO_SPREADS_SERIES_ID,
    MIN_KCRORO_SESSIONS_HARD,
    MIN_KCRORO_SESSIONS_RECOMMENDED,
    MIN_NFCI_WEEKS_HARD,
    MIN_NFCI_WEEKS_RECOMMENDED,
    NFCI_RELEASE_LAG_CALENDAR_DAYS,
    NFCI_SERIES_ID,
    RELEASE_LAG_CALENDAR_DAYS,
    kcroro_recipe_manifest,
)
from config.settings import (
    ALFRED_BASE_URL,
    FRED_BASE_URL,
    FRED_PUBLIC_CSV_URL,
    settings,
)


_log = logging.getLogger(__name__)
RESEARCH_TIMEOUT_SECONDS = 30
SUBINDEX_SERIES = (
    KCRORO_SPREADS_SERIES_ID,
    KCRORO_EQUITY_SERIES_ID,
    KCRORO_LIQUIDITY_SERIES_ID,
    KCRORO_FXGOLD_SERIES_ID,
)


@dataclass(frozen=True)
class KcroroObservation:
    observation_date: date
    release_date: date
    kcroro: float
    spreads: float | None
    equities: float | None
    liquidity: float | None
    fx_gold: float | None
    release_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_date": self.observation_date.isoformat(),
            "release_date": self.release_date.isoformat(),
            "kcroro": self.kcroro,
            "spreads": self.spreads,
            "equities": self.equities,
            "liquidity": self.liquidity,
            "fx_gold": self.fx_gold,
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
class KcroroSeriesBundle:
    status: str
    source: str
    retrieved_at: str
    observations: tuple[KcroroObservation, ...] = field(default_factory=tuple)
    hy_observations: tuple[HyKeepObservation, ...] = field(default_factory=tuple)
    nfci_observations: tuple[NfciKeepObservation, ...] = field(default_factory=tuple)
    kcroro_count: int = 0
    spreads_count: int = 0
    equities_count: int = 0
    liquidity_count: int = 0
    fx_gold_count: int = 0
    hy_count: int = 0
    ig_count: int = 0
    nfci_count: int = 0
    first_release_date: date | None = None
    last_release_date: date | None = None
    message: str | None = None
    ice_redistribution_notice: str = ICE_REDISTRIBUTION_NOTICE
    citation: str = KCRORO_CITATION
    history_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["observations"] = [row.to_dict() for row in self.observations]
        payload["hy_observations"] = [row.to_dict() for row in self.hy_observations]
        payload["nfci_observations"] = [row.to_dict() for row in self.nfci_observations]
        payload["first_release_date"] = (
            self.first_release_date.isoformat() if self.first_release_date else None
        )
        payload["last_release_date"] = (
            self.last_release_date.isoformat() if self.last_release_date else None
        )
        payload["observation_count"] = len(self.observations)
        payload["recipe"] = kcroro_recipe_manifest()
        return payload


class KcroroClient:
    """Research-only FRED/ALFRED ingest for daily KCRORO plus KEEP HY OAS and NFCI.

    Joins must use release_date, not the observation date. This client is not a
    live overlay and does not add KCRORO to the live FRED macro bundle.
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
        include_keep_comparators: bool = True,
        include_subindexes: bool = True,
    ) -> None:
        self.api_key = (api_key if api_key is not None else settings.fred_api_key).strip()
        self.fred_base_url = fred_base_url.rstrip("/")
        self.alfred_base_url = alfred_base_url.rstrip("/")
        self.public_csv_url = public_csv_url
        self.timeout_seconds = timeout_seconds
        self.allow_public_csv = allow_public_csv
        self.include_keep_comparators = include_keep_comparators
        self.include_subindexes = include_subindexes

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self.allow_public_csv

    def fetch_bundle(self) -> KcroroSeriesBundle:
        retrieved_at = datetime.now(UTC).isoformat()
        kcroro_error: str | None = None
        hy_error: str | None = None
        ig_error: str | None = None
        nfci_error: str | None = None
        kcroro_source = "unavailable"
        hy_source = "unavailable"
        ig_source = "unavailable"
        nfci_source = "unavailable"
        try:
            kcroro_rows, kcroro_source = self._fetch_kcroro()
        except Exception as exc:
            _log.warning("KCRORO series %s was unavailable.", KCRORO_SERIES_ID, exc_info=True)
            kcroro_rows = ()
            kcroro_error = f"{KCRORO_SERIES_ID} unavailable ({exc.__class__.__name__})"

        hy_points: dict[date, float] = {}
        ig_points: dict[date, float] = {}
        nfci_rows: tuple[NfciKeepObservation, ...] = ()
        if self.include_keep_comparators:
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
            try:
                nfci_rows, nfci_source = self._fetch_nfci()
            except Exception as exc:
                _log.warning("NFCI series %s was unavailable.", NFCI_SERIES_ID, exc_info=True)
                nfci_error = f"{NFCI_SERIES_ID} unavailable ({exc.__class__.__name__})"

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
        kcroro_count = len(kcroro_rows)
        spreads_count = sum(row.spreads is not None for row in kcroro_rows)
        equities_count = sum(row.equities is not None for row in kcroro_rows)
        liquidity_count = sum(row.liquidity is not None for row in kcroro_rows)
        fx_gold_count = sum(row.fx_gold is not None for row in kcroro_rows)
        hy_count = sum(row.hy_oas is not None for row in hy_observations)
        ig_count = sum(row.ig_oas is not None for row in hy_observations)
        nfci_count = len(nfci_rows)
        errors = [item for item in (kcroro_error, hy_error, ig_error, nfci_error) if item]
        non_equity_ready = (
            spreads_count >= MIN_KCRORO_SESSIONS_HARD
            and liquidity_count >= MIN_KCRORO_SESSIONS_HARD
            and fx_gold_count >= MIN_KCRORO_SESSIONS_HARD
        )
        history_plan = {
            "kcroro_source": kcroro_source,
            "hy_source": hy_source,
            "ig_source": ig_source,
            "nfci_source": nfci_source,
            "kcroro_count": kcroro_count,
            "spreads_count": spreads_count,
            "equities_count": equities_count,
            "liquidity_count": liquidity_count,
            "fx_gold_count": fx_gold_count,
            "hy_count": hy_count,
            "ig_count": ig_count,
            "nfci_count": nfci_count,
            "min_kcroro_sessions_hard": MIN_KCRORO_SESSIONS_HARD,
            "min_kcroro_sessions_recommended": MIN_KCRORO_SESSIONS_RECOMMENDED,
            "min_hy_sessions_hard": HY_MIN_SERIES_SESSIONS_HARD,
            "min_hy_sessions_recommended": HY_MIN_SERIES_SESSIONS_RECOMMENDED,
            "min_nfci_weeks_hard": MIN_NFCI_WEEKS_HARD,
            "min_nfci_weeks_recommended": MIN_NFCI_WEEKS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
            "release_lag_calendar_days": RELEASE_LAG_CALENDAR_DAYS,
            "meets_kcroro_hard_minimum": kcroro_count >= MIN_KCRORO_SESSIONS_HARD,
            "meets_hy_hard_minimum": hy_count >= HY_MIN_SERIES_SESSIONS_HARD,
            "meets_nfci_hard_minimum": nfci_count >= MIN_NFCI_WEEKS_HARD,
            "non_equity_ablation_ready": non_equity_ready,
            "data_blocked": kcroro_count < MIN_KCRORO_SESSIONS_HARD,
            "hy_keep_unavailable": hy_count < HY_MIN_SERIES_SESSIONS_HARD,
            "nfci_keep_unavailable": nfci_count < MIN_NFCI_WEEKS_HARD,
        }
        if kcroro_count == 0:
            status = "unavailable"
            message = "; ".join(errors) if errors else "KCRORO observations were empty."
        elif kcroro_count < MIN_KCRORO_SESSIONS_HARD:
            status = "data_blocked"
            message = (
                f"{KCRORO_SERIES_ID} returned {kcroro_count} daily observations; "
                f"{MIN_KCRORO_SESSIONS_HARD} are required for the frozen recipe. "
                "FAIL data-blocked."
            )
        elif hy_count < HY_MIN_SERIES_SESSIONS_HARD or nfci_count < MIN_NFCI_WEEKS_HARD:
            status = "partial"
            missing: list[str] = []
            if hy_count < HY_MIN_SERIES_SESSIONS_HARD:
                missing.append(
                    f"KEEP HY OAS has {hy_count} sessions (need {HY_MIN_SERIES_SESSIONS_HARD})"
                )
            if nfci_count < MIN_NFCI_WEEKS_HARD:
                missing.append(
                    f"KEEP NFCI has {nfci_count} weeks (need {MIN_NFCI_WEEKS_HARD})"
                )
            message = (
                f"{KCRORO_SERIES_ID} ingested from {kcroro_source} with {kcroro_count} sessions, "
                f"but {'; '.join(missing)}. Nested kill-switch vs HY OAS + NFCI cannot be scored."
            )
        else:
            status = "available"
            message = None
            notes: list[str] = []
            if kcroro_count < MIN_KCRORO_SESSIONS_RECOMMENDED:
                notes.append(
                    f"{KCRORO_SERIES_ID} has {kcroro_count} sessions, below the recommended "
                    f"{MIN_KCRORO_SESSIONS_RECOMMENDED}-session budget, but the hard minimum "
                    "for the frozen recipe is met."
                )
            if not non_equity_ready:
                notes.append(
                    "Non-equity subindexes are short of the hard minimum; equity-leg ablation "
                    "cannot be scored until KCROROS/L/G meet 252 sessions."
                )
            if notes:
                message = " ".join(notes)
        return KcroroSeriesBundle(
            status=status,
            source=_combined_source(kcroro_source, hy_source, nfci_source),
            retrieved_at=retrieved_at,
            observations=kcroro_rows,
            hy_observations=hy_observations,
            nfci_observations=nfci_rows,
            kcroro_count=kcroro_count,
            spreads_count=spreads_count,
            equities_count=equities_count,
            liquidity_count=liquidity_count,
            fx_gold_count=fx_gold_count,
            hy_count=hy_count,
            ig_count=ig_count,
            nfci_count=nfci_count,
            first_release_date=kcroro_rows[0].release_date if kcroro_rows else None,
            last_release_date=kcroro_rows[-1].release_date if kcroro_rows else None,
            message=message,
            history_plan=history_plan,
        )

    def _fetch_kcroro(self) -> tuple[tuple[KcroroObservation, ...], str]:
        if self.api_key:
            vintage_rows = self._fred_kcroro_initial_release()
            if vintage_rows:
                return vintage_rows, "fred_alfred_initial_release"
            current_rows = self._kcroro_from_points(
                self._fred_observations(KCRORO_SERIES_ID),
                subindexes=self._fetch_subindexes(prefer="fred_api"),
                release_source="fred_api_release_lag",
            )
            if current_rows:
                return current_rows, "fred_api_release_lag"
        if self.allow_public_csv:
            csv_rows = self._kcroro_from_points(
                self._public_csv_observations(KCRORO_SERIES_ID),
                subindexes=self._fetch_subindexes(prefer="fred_public_csv"),
                release_source="fred_public_csv_release_lag",
            )
            if csv_rows:
                return csv_rows, "fred_public_csv_release_lag"
        raise RuntimeError(f"{KCRORO_SERIES_ID} returned no observations")

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

    def _fetch_subindexes(self, *, prefer: str) -> dict[str, dict[date, float]]:
        if not self.include_subindexes:
            return {}
        loaded: dict[str, dict[date, float]] = {}
        for series_id in SUBINDEX_SERIES:
            try:
                if prefer == "fred_api" and self.api_key:
                    loaded[series_id] = self._fred_observations(series_id)
                elif self.allow_public_csv:
                    loaded[series_id] = self._public_csv_observations(series_id)
            except Exception:
                _log.warning("KCRORO subindex %s was unavailable.", series_id, exc_info=True)
        return loaded

    def _fred_kcroro_initial_release(self) -> tuple[KcroroObservation, ...]:
        query = urlencode(
            {
                "series_id": KCRORO_SERIES_ID,
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
            _log.warning("ALFRED-style KCRORO vintage window failed.", exc_info=True)
            return ()
        first_release = _first_release_from_vintage_payload(payload, fallback_lag=RELEASE_LAG_CALENDAR_DAYS)
        if not first_release:
            return ()
        subindexes = self._fetch_subindexes(prefer="fred_api")
        return tuple(
            KcroroObservation(
                observation_date=as_of,
                release_date=release,
                kcroro=value,
                spreads=_lookup(subindexes, KCRORO_SPREADS_SERIES_ID, as_of),
                equities=_lookup(subindexes, KCRORO_EQUITY_SERIES_ID, as_of),
                liquidity=_lookup(subindexes, KCRORO_LIQUIDITY_SERIES_ID, as_of),
                fx_gold=_lookup(subindexes, KCRORO_FXGOLD_SERIES_ID, as_of),
                release_source=source,
            )
            for as_of, (release, value, source) in sorted(first_release.items())
        )

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
        first_release = _first_release_from_vintage_payload(
            payload,
            fallback_lag=NFCI_RELEASE_LAG_CALENDAR_DAYS,
        )
        return tuple(
            NfciKeepObservation(
                observation_week_end=week_end,
                release_date=release,
                nfci=value,
                release_source=source,
            )
            for week_end, (release, value, source) in sorted(first_release.items())
        )

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

    def _kcroro_from_points(
        self,
        points: dict[date, float],
        *,
        subindexes: dict[str, dict[date, float]],
        release_source: str,
    ) -> tuple[KcroroObservation, ...]:
        rows = [
            KcroroObservation(
                observation_date=as_of,
                release_date=_fallback_release_date(as_of, RELEASE_LAG_CALENDAR_DAYS),
                kcroro=value,
                spreads=_lookup(subindexes, KCRORO_SPREADS_SERIES_ID, as_of),
                equities=_lookup(subindexes, KCRORO_EQUITY_SERIES_ID, as_of),
                liquidity=_lookup(subindexes, KCRORO_LIQUIDITY_SERIES_ID, as_of),
                fx_gold=_lookup(subindexes, KCRORO_FXGOLD_SERIES_ID, as_of),
                release_source=release_source,
            )
            for as_of, value in sorted(points.items())
        ]
        return tuple(rows)

    def _nfci_from_points(
        self,
        points: dict[date, float],
        *,
        release_source: str,
    ) -> tuple[NfciKeepObservation, ...]:
        return tuple(
            NfciKeepObservation(
                observation_week_end=week_end,
                release_date=_fallback_release_date(week_end, NFCI_RELEASE_LAG_CALENDAR_DAYS),
                nfci=value,
                release_source=release_source,
            )
            for week_end, value in sorted(points.items())
        )

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


def build_kcroro_client() -> KcroroClient:
    return KcroroClient()


def _first_release_from_vintage_payload(
    payload: dict[str, Any],
    *,
    fallback_lag: int,
) -> dict[date, tuple[date, float, str]]:
    first_release: dict[date, tuple[date, float, str]] = {}
    for item in payload.get("observations", []):
        parsed = _parse_observation(item.get("date"), item.get("value"))
        if parsed is None:
            continue
        as_of, value = parsed
        realtime = _parse_date(item.get("realtime_start"))
        if realtime is None:
            release = _fallback_release_date(as_of, fallback_lag)
            source = "fred_api_release_lag"
        else:
            release = realtime
            source = "alfred_initial_release"
        current = first_release.get(as_of)
        if current is None or release < current[0]:
            first_release[as_of] = (release, value, source)
    return first_release


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


def _fallback_release_date(as_of: date, lag_days: int) -> date:
    return as_of + timedelta(days=lag_days)


def _lookup(series: dict[str, dict[date, float]], series_id: str, as_of: date) -> float | None:
    points = series.get(series_id) or {}
    return points.get(as_of)


def _combined_source(kcroro_source: str, hy_source: str, nfci_source: str) -> str:
    parts = [kcroro_source]
    if hy_source not in {"unavailable", ""}:
        parts.append(hy_source)
    if nfci_source not in {"unavailable", ""}:
        parts.append(nfci_source)
    unique = list(dict.fromkeys(parts))
    return unique[0] if len(unique) == 1 else "+".join(unique)


__all__ = [
    "HyKeepObservation",
    "KcroroClient",
    "KcroroObservation",
    "KcroroSeriesBundle",
    "NfciKeepObservation",
    "build_kcroro_client",
]
