from __future__ import annotations

from typing import Any

from domain.etf.models import EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile, optional_float, optional_int, optional_str
from domain.etf.normalization import normalize_allocation, normalize_holdings, with_unavailable_fields
from providers.news.finnhub_client import FinnhubClient, build_finnhub_client


class FinnhubEtfProvider:
    name = "finnhub"

    def __init__(self, client: FinnhubClient | None = None) -> None:
        self._client = client or build_finnhub_client()

    @property
    def enabled(self) -> bool:
        return self._client.enabled

    def get_profile(self, ticker: str) -> EtfProfile | None:
        if not self.enabled:
            return None
        normalized = ticker.upper().strip()
        response = self._client._request("etf/profile", {"symbol": normalized})
        payload = response.payload if isinstance(response.payload, dict) else None
        if payload is None:
            return None
        profile_payload = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        if not profile_payload:
            return None
        sector_response = self._client._request("etf/sector", {"symbol": normalized})
        country_response = self._client._request("etf/country", {"symbol": normalized})
        profile = EtfProfile(
            ticker=normalized,
            name=optional_str(profile_payload.get("name") or profile_payload.get("longName")),
            issuer=optional_str(profile_payload.get("fundFamily") or profile_payload.get("companyName") or profile_payload.get("issuer")),
            asset_class=optional_str(profile_payload.get("assetClass") or profile_payload.get("assetType")),
            category=optional_str(profile_payload.get("investmentSegment") or profile_payload.get("category")),
            description=optional_str(profile_payload.get("description")),
            expense_ratio=optional_float(profile_payload.get("expenseRatio")),
            aum=optional_float(profile_payload.get("aum") or profile_payload.get("totalNav")),
            average_volume=optional_float(profile_payload.get("averageVolume") or profile_payload.get("avgVolume")),
            dividend_yield=optional_float(profile_payload.get("yield") or profile_payload.get("dividendYield")),
            inception_date=optional_str(profile_payload.get("inceptionDate") or profile_payload.get("inception")),
            holdings_count=optional_int(profile_payload.get("holdingsCount") or profile_payload.get("numberOfHoldings")),
            geographic_exposure=normalize_allocation(_list_payload(country_response.payload, "countries", "country"), self.name),
            sector_exposure=normalize_allocation(_list_payload(sector_response.payload, "sectors", "sector"), self.name),
            source=self.name,
            quote_type="ETF",
        )
        return with_unavailable_fields(profile)

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        if not self.enabled:
            return None
        normalized = ticker.upper().strip()
        response = self._client._request("etf/holdings", {"symbol": normalized})
        payload = response.payload
        holdings_payload = _list_payload(payload, "holdings", None)
        if not holdings_payload:
            return None
        as_of = None
        if isinstance(payload, dict):
            as_of = optional_str(payload.get("atDate") or payload.get("asOfDate"))
        return normalize_holdings(normalized, holdings_payload, source=self.name, as_of=as_of)

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        return []

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        return EtfFlowSnapshot(
            ticker=ticker.upper().strip(),
            available=False,
            source=self.name,
            unavailable_reason="Finnhub ETF fund-flow data is not configured for this deployment.",
        )

    def search(self, query: str) -> list[EtfProfile]:
        if not self.enabled:
            return []
        ticker = query.upper().strip()
        profile = self.get_profile(ticker) if ticker else None
        return [profile] if profile is not None else []


def _list_payload(payload: Any, key: str | None, label_key: str | None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and key:
        rows = payload.get(key) or payload.get("data") or []
    else:
        rows = []
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if label_key and label_key not in item and "label" not in item:
            item = {**item, "label": item.get(label_key) or item.get("name")}
        normalized.append(item)
    return normalized


__all__ = ["FinnhubEtfProvider"]
