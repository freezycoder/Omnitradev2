from __future__ import annotations

from domain.etf.models import EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile
from providers.etf.composite import CompositeEtfProvider


class _BoomProvider:
    enabled = True

    def get_profile(self, ticker: str):
        raise RuntimeError(f"profile failed for {ticker}")

    def get_holdings(self, ticker: str):
        raise RuntimeError(f"holdings failed for {ticker}")

    def get_flows(self, ticker: str):
        return EtfFlowSnapshot(ticker=ticker, available=False)


class _OkProvider:
    enabled = True

    def get_profile(self, ticker: str):
        return EtfProfile(ticker=ticker, name="Fallback ETF", quote_type="ETF")

    def get_holdings(self, ticker: str):
        return None

    def get_flows(self, ticker: str):
        return EtfFlowSnapshot(ticker=ticker, available=False)


def test_composite_profile_swallows_provider_exceptions():
    provider = CompositeEtfProvider(finnhub_provider=_BoomProvider(), yfinance_provider=_OkProvider())
    profile = provider.get_profile("QQQ")
    assert profile is not None
    assert profile.ticker == "QQQ"
    assert profile.name == "Fallback ETF"


def test_composite_holdings_swallows_provider_exceptions():
    provider = CompositeEtfProvider(finnhub_provider=_BoomProvider(), yfinance_provider=_BoomProvider())
    assert provider.get_holdings("QQQ") is None
