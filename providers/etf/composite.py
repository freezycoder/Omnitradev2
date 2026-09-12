from __future__ import annotations

from domain.etf.models import AllocationSlice, EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile, optional_str
from domain.etf.normalization import with_unavailable_fields
from providers.etf.finnhub_provider import FinnhubEtfProvider
from providers.etf.yfinance_provider import YFinanceEtfProvider


def _prefer(primary: str | None, secondary: str | None) -> str | None:
    return optional_str(primary) or optional_str(secondary)


def _merge_allocations(
    primary: tuple[AllocationSlice, ...],
    secondary: tuple[AllocationSlice, ...],
) -> tuple[AllocationSlice, ...]:
    return primary or secondary


def merge_profiles(primary: EtfProfile | None, secondary: EtfProfile | None) -> EtfProfile | None:
    if primary is None:
        return secondary
    if secondary is None:
        return primary
    sources = [item for item in (primary.source, secondary.source) if item]
    merged = EtfProfile(
        ticker=primary.ticker,
        name=_prefer(primary.name, secondary.name),
        issuer=_prefer(primary.issuer, secondary.issuer),
        asset_class=_prefer(primary.asset_class, secondary.asset_class),
        category=_prefer(primary.category, secondary.category),
        description=_prefer(primary.description, secondary.description),
        expense_ratio=primary.expense_ratio if primary.expense_ratio is not None else secondary.expense_ratio,
        aum=primary.aum if primary.aum is not None else secondary.aum,
        average_volume=primary.average_volume if primary.average_volume is not None else secondary.average_volume,
        dividend_yield=primary.dividend_yield if primary.dividend_yield is not None else secondary.dividend_yield,
        inception_date=_prefer(primary.inception_date, secondary.inception_date),
        holdings_count=primary.holdings_count if primary.holdings_count is not None else secondary.holdings_count,
        geographic_exposure=_merge_allocations(primary.geographic_exposure, secondary.geographic_exposure),
        sector_exposure=_merge_allocations(primary.sector_exposure, secondary.sector_exposure),
        source="+".join(dict.fromkeys(sources)) or None,
        quote_type=_prefer(primary.quote_type, secondary.quote_type),
        updated_at=primary.updated_at or secondary.updated_at,
    )
    return with_unavailable_fields(merged)


class CompositeEtfProvider:
    name = "composite"

    def __init__(
        self,
        finnhub_provider: FinnhubEtfProvider | None = None,
        yfinance_provider: YFinanceEtfProvider | None = None,
    ) -> None:
        self._finnhub = finnhub_provider or FinnhubEtfProvider()
        self._yfinance = yfinance_provider or YFinanceEtfProvider()

    def get_profile(self, ticker: str) -> EtfProfile | None:
        finnhub_profile = self._finnhub.get_profile(ticker) if self._finnhub.enabled else None
        yfinance_profile = self._yfinance.get_profile(ticker)
        return merge_profiles(finnhub_profile, yfinance_profile)

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        if self._finnhub.enabled:
            holdings = self._finnhub.get_holdings(ticker)
            if holdings is not None and holdings.holdings:
                return holdings
        return self._yfinance.get_holdings(ticker)

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        return []

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        finnhub_flows = self._finnhub.get_flows(ticker)
        if finnhub_flows.available:
            return finnhub_flows
        return self._yfinance.get_flows(ticker)

    def search(self, query: str) -> list[EtfProfile]:
        found = self._finnhub.search(query)
        if found:
            return found
        return self._yfinance.search(query)


def build_etf_provider() -> CompositeEtfProvider:
    return CompositeEtfProvider()


__all__ = ["CompositeEtfProvider", "build_etf_provider", "merge_profiles"]
