from __future__ import annotations

import pytest

from domain.etf.models import EtfFlowSnapshot, EtfHolding, EtfHoldingsSnapshot, EtfProfile
from domain.etf.overlap import pairwise_overlap
from storage.repositories.etf_repository import EtfRepository
from storage.sqlite import initialize_database


class FakeEtfProvider:
    name = "fake"

    def __init__(self) -> None:
        self.profiles = {
            "QQQ": EtfProfile(ticker="QQQ", name="Invesco QQQ Trust", issuer="Invesco", quote_type="ETF", category="Large Growth"),
            "SPY": EtfProfile(ticker="SPY", name="SPDR S&P 500", issuer="SSGA", quote_type="ETF", category="Large Blend"),
        }
        self.holdings = {
            "QQQ": EtfHoldingsSnapshot(
                etf_ticker="QQQ",
                captured_at="2026-09-12T00:00:00+00:00",
                source="fake",
                holdings=(
                    EtfHolding("QQQ", "AAPL", "Apple", 0.10),
                    EtfHolding("QQQ", "MSFT", "Microsoft", 0.20),
                ),
            ),
            "SPY": EtfHoldingsSnapshot(
                etf_ticker="SPY",
                captured_at="2026-09-12T00:00:00+00:00",
                source="fake",
                holdings=(
                    EtfHolding("SPY", "AAPL", "Apple", 0.05),
                    EtfHolding("SPY", "MSFT", "Microsoft", 0.10),
                ),
            ),
        }

    def get_profile(self, ticker: str) -> EtfProfile | None:
        return self.profiles.get(ticker.upper())

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        return self.holdings.get(ticker.upper())

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        return []

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        return EtfFlowSnapshot(ticker=ticker.upper(), available=False, unavailable_reason="Flows are not published.")

    def search(self, query: str) -> list[EtfProfile]:
        profile = self.get_profile(query)
        return [profile] if profile else []


def test_holdings_and_overlap_use_repository_not_invented_data(tmp_path):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    repo = EtfRepository(db_path)
    provider = FakeEtfProvider()
    for ticker in ("QQQ", "SPY"):
        repo.upsert_profile(provider.get_profile(ticker))
        repo.replace_holdings(provider.get_holdings(ticker))

    qqq = repo.get_holdings("QQQ")
    spy = repo.get_holdings("SPY")
    reverse = repo.list_holdings_for_stock("AAPL")

    assert pairwise_overlap(qqq.holdings, spy.holdings) == pytest.approx(0.15)
    assert {item.etf_ticker for item in reverse} == {"QQQ", "SPY"}


def test_missing_holdings_stay_none(tmp_path):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    repo = EtfRepository(db_path)

    assert repo.get_holdings("ARKK") is None
    assert repo.get_profile("ARKK") is None


def test_screener_filters_skip_unknown_numeric_fields():
    from application.etf_service import _row_matches
    from config.etf import EtfUniverseFilters

    row = {
        "ticker": "QQQ",
        "name": "Invesco QQQ",
        "issuer": "Invesco",
        "asset_class": "Equity",
        "category": "Large Growth",
        "sector": "Technology",
        "geography": "United States",
        "expense_ratio": 0.002,
        "aum": None,
        "average_volume": 40_000_000,
        "dividend_yield": None,
    }

    assert _row_matches(row, EtfUniverseFilters(sector="tech", geography="united"))
    assert not _row_matches(row, EtfUniverseFilters(min_aum=1_000_000))
    assert not _row_matches(row, EtfUniverseFilters(min_dividend_yield=0.01))
    assert _row_matches(row, EtfUniverseFilters(max_expense_ratio=0.01))

