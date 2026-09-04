from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.settings import FINNHUB_BASE_URL, FINNHUB_NEWS_LOOKBACK_DAYS, FINNHUB_TIMEOUT_SECONDS, settings


_log = logging.getLogger(__name__)


@dataclass
class FinnhubResponse:
    payload: Any
    error: str | None = None


class FinnhubClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = FINNHUB_BASE_URL,
        timeout_seconds: int = FINNHUB_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _request(self, path: str, params: dict[str, Any]) -> FinnhubResponse:
        if not self.enabled:
            return FinnhubResponse(payload=None, error="Finnhub API key is not configured.")

        query = urlencode({**params, "token": self.api_key})
        request = Request(
            f"{self.base_url}/{path}?{query}",
            headers={"Accept": "application/json", "User-Agent": "stock-dashboard/1.0"},
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                _log.warning("Finnhub %s returned 429 (rate limit reached).", path)
                return FinnhubResponse(payload=None, error="Finnhub rate limit reached.")
            _log.error("Finnhub %s returned HTTP %s.", path, exc.code, exc_info=True)
            return FinnhubResponse(payload=None, error=f"Finnhub HTTP {exc.code}.")
        except (URLError, TimeoutError):
            _log.error(
                "Finnhub %s unreachable (URLError/TimeoutError); returning unavailable error.",
                path,
                exc_info=True,
            )
            return FinnhubResponse(payload=None, error="Finnhub is unavailable right now.")
        except Exception:
            _log.error(
                "Finnhub %s response could not be parsed; returning parse error to caller.",
                path,
                exc_info=True,
            )
            return FinnhubResponse(payload=None, error="Finnhub response could not be parsed.")

        if isinstance(payload, dict) and payload.get("error"):
            return FinnhubResponse(payload=None, error=str(payload["error"]))
        return FinnhubResponse(payload=payload, error=None)

    def get_quote(self, ticker: str) -> FinnhubResponse:
        return self._request("quote", {"symbol": ticker.upper().strip()})

    def get_company_profile(self, ticker: str) -> FinnhubResponse:
        return self._request("stock/profile2", {"symbol": ticker.upper().strip()})

    def get_company_news(self, ticker: str, days_back: int = FINNHUB_NEWS_LOOKBACK_DAYS) -> FinnhubResponse:
        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)
        return self._request(
            "company-news",
            {
                "symbol": ticker.upper().strip(),
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
            },
        )

    def get_company_earnings(self, ticker: str, limit: int = 4) -> FinnhubResponse:
        return self._request(
            "stock/earnings",
            {
                "symbol": ticker.upper().strip(),
                "limit": max(1, min(int(limit), 12)),
            },
        )


def build_finnhub_client() -> FinnhubClient:
    return FinnhubClient(api_key=settings.finnhub_api_key)
