from __future__ import annotations

from datetime import date
from urllib.error import HTTPError

from providers.market.finra_short_interest_client import (
    FinraShortInterestClient,
    latest_published_settlement,
    parse_short_interest_record,
    publication_date_from_settlement,
    reset_finra_short_interest_caches,
)


SAMPLE_AAPL = {
    "symbolCode": "AAPL",
    "issueName": "Apple Inc. Common Stock",
    "currentShortPositionQuantity": 141606163,
    "previousShortPositionQuantity": 146547784,
    "changePercent": -3.37,
    "daysToCoverQuantity": 2.42,
    "averageDailyVolumeQuantity": 58400983,
    "settlementDate": "2026-07-31",
    "marketClassCode": "NNM",
    "revisionFlag": None,
}

SAMPLE_OTC = {
    "securitiesInformationProcessorSymbolIdentifier": "AABB",
    "currentShortShareNumber": 14,
    "previousShortShareNumber": 510423,
    "changePercent": -100,
    "daysToCoverNumber": 1,
    "settlementDate": "2026-07-31",
}


def test_publication_date_is_seventh_weekday_not_settlement():
    # Friday 2026-07-31 published on Tuesday 2026-08-11 per Rule 4560 weekday lag.
    settlement = date(2026, 7, 31)
    published = publication_date_from_settlement(settlement)

    assert published == date(2026, 8, 11)
    assert published != settlement
    assert (published - settlement).days >= 8


def test_latest_published_settlement_waits_for_publication_lag():
    # On settlement day the cycle is not yet public.
    as_of = date(2026, 7, 31)
    latest = latest_published_settlement(as_of)
    assert latest is not None
    assert publication_date_from_settlement(latest) <= as_of
    assert latest < as_of


def test_parse_consolidated_and_standardized_aliases():
    listed = parse_short_interest_record(SAMPLE_AAPL)
    otc = parse_short_interest_record(SAMPLE_OTC)

    assert listed is not None
    assert listed.symbol == "AAPL"
    assert listed.short_shares == 141606163
    assert listed.pct_change_prior == -3.37
    assert listed.days_to_cover == 2.42
    assert listed.event_date == date(2026, 8, 11)
    assert listed.settlement_date == date(2026, 7, 31)
    assert otc is not None
    assert otc.symbol == "AABB"
    assert otc.short_shares == 14


def test_client_uses_cached_cycle_and_looks_up_symbol(tmp_path):
    reset_finra_short_interest_caches()
    fetched: list[str] = []

    def fake_fetch(url: str, body: bytes | None) -> bytes:
        fetched.append(url)
        if "consolidatedShortInterest" in url:
            return (
                b'[{"symbolCode":"AAPL","currentShortPositionQuantity":100,'
                b'"previousShortPositionQuantity":80,"changePercent":25.0,'
                b'"daysToCoverQuantity":6.2,"settlementDate":"2026-07-31"}]'
            )
        raise HTTPError(url, 404, "missing", hdrs=None, fp=None)

    client = FinraShortInterestClient(cache_dir=tmp_path, fetch_bytes=fake_fetch)
    first = client.fetch_settlement(date(2026, 7, 31))
    second = client.fetch_settlement(date(2026, 7, 31))
    row = first.row_for_symbol("aapl")

    assert first.status == "available"
    assert first.publication_date == date(2026, 8, 11)
    assert row is not None
    assert row.pct_change_prior == 25.0
    assert row.days_to_cover == 6.2
    assert second.row_for_symbol("AAPL").short_shares == 100
    assert fetched.count(
        "https://api.finra.org/data/group/otcMarket/name/consolidatedShortInterest"
    ) == 1
    assert (tmp_path / "consolidatedShortInterest_20260731.json").exists()
