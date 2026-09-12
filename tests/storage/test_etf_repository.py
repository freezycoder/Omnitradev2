from __future__ import annotations

from domain.etf.models import EtfHolding, EtfHoldingsSnapshot, EtfProfile
from storage.repositories.etf_repository import EtfRepository
from storage.sqlite import initialize_database


def test_etf_repository_round_trips_profiles_and_holdings(tmp_path):
    db_path = tmp_path / "omnitrade.db"
    initialize_database(db_path)
    repo = EtfRepository(db_path)
    profile = EtfProfile(ticker="QQQ", name="Invesco QQQ", issuer="Invesco", expense_ratio=0.002, aum=250_000_000_000)
    repo.upsert_profile(profile)
    snapshot = EtfHoldingsSnapshot(
        etf_ticker="QQQ",
        captured_at="2026-09-12T00:00:00+00:00",
        source="test",
        holdings=(
            EtfHolding("QQQ", "AAPL", "Apple", 0.10),
            EtfHolding("QQQ", "MSFT", "Microsoft", 0.09),
        ),
    )
    repo.replace_holdings(snapshot)

    stored = repo.get_profile("qqq")
    holdings = repo.get_holdings("QQQ")
    reverse = repo.list_holdings_for_stock("AAPL")

    assert stored is not None
    assert stored.name == "Invesco QQQ"
    assert holdings is not None
    assert holdings.holdings_count == 2
    assert reverse[0].etf_ticker == "QQQ"


def test_repository_does_not_treat_missing_aum_as_zero(tmp_path):
    db_path = tmp_path / "omnitrade.db"
    initialize_database(db_path)
    repo = EtfRepository(db_path)
    repo.upsert_profile(EtfProfile(ticker="GLD", name="SPDR Gold", aum=None, expense_ratio=None))

    stored = repo.get_profile("GLD")

    assert stored is not None
    assert stored.aum is None
    assert stored.expense_ratio is None
