from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.section16 import (
    TRACEFOUR_ANONYMOUS_RATE_LIMIT_PER_HOUR,
    TRACEFOUR_ATTRIBUTION,
    TRACEFOUR_BASE_URL,
    TRACEFOUR_KEYED_RATE_LIMIT_PER_HOUR,
    TRACEFOUR_LICENSE,
)
from config.settings import settings


_log = logging.getLogger(__name__)

# Tracefour is a secondary digest only. The Section-16 experiment never treats
# it as the primary event stream. Anonymous reads are 60 req/hour per IP;
# a free bearer key raises that to 600 req/hour. Compilation is CC BY 4.0 and
# requires attribution to the page named in meta.attribution.page.


@dataclass(frozen=True)
class TracefourTerms:
    base_url: str = TRACEFOUR_BASE_URL
    anonymous_rate_limit_per_hour: int = TRACEFOUR_ANONYMOUS_RATE_LIMIT_PER_HOUR
    keyed_rate_limit_per_hour: int = TRACEFOUR_KEYED_RATE_LIMIT_PER_HOUR
    license: str = TRACEFOUR_LICENSE
    attribution: str = TRACEFOUR_ATTRIBUTION
    docs_url: str = "https://tracefour.com/api-docs"
    role: str = "optional_secondary_digest_cross_check"
    never_primary: bool = True


class TracefourClient:
    def __init__(
        self,
        *,
        base_url: str = TRACEFOUR_BASE_URL,
        api_key: str | None = None,
        timeout_seconds: int = 20,
        enabled: bool = False,
        min_request_interval_seconds: float = 1.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_at = 0.0

    @property
    def terms(self) -> TracefourTerms:
        return TracefourTerms(base_url=self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": settings.sec_edgar_user_agent or "OmniTrade research (section16-shadow)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.enabled:
            return {
                "data": [],
                "error": "Tracefour is disabled; SEC remains the primary Section-16 path.",
                "meta": {"source": "disabled", "terms": self.terms.__dict__},
            }
        wait_seconds = self.min_request_interval_seconds - (time.monotonic() - self._last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        query = f"?{urlencode(params)}" if params else ""
        url = f"{self.base_url}{path}{query}"
        request = Request(url, headers=self._headers())
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                _log.info("Tracefour rate limit reached.")
                return {"data": [], "error": "rate_limited", "meta": {"http_status": 429}}
            _log.info("Tracefour HTTP %s for %s.", exc.code, path)
            return {"data": [], "error": f"http_{exc.code}", "meta": {"http_status": exc.code}}
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError):
            _log.info("Tracefour request failed for %s.", path, exc_info=True)
            return {"data": [], "error": "unavailable", "meta": {}}
        finally:
            self._last_request_at = time.monotonic()
        if not isinstance(payload, dict):
            return {"data": [], "error": "unexpected_payload", "meta": {}}
        return payload

    def get_filings(
        self,
        *,
        direction: str = "all",
        ticker: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"direction": direction, "limit": max(1, min(int(limit), 500))}
        if ticker:
            params["ticker"] = ticker.upper().strip()
        if since:
            params["since"] = since
        return self._get("/v1/filings", params)

    def get_clusters(self) -> dict[str, Any]:
        return self._get("/v1/clusters")

    def get_streaks(self) -> dict[str, Any]:
        return self._get("/v1/streaks")


def build_tracefour_client(*, enabled: bool = False) -> TracefourClient:
    return TracefourClient(enabled=enabled)


__all__ = ["TracefourClient", "TracefourTerms", "build_tracefour_client"]
