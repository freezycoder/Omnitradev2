from __future__ import annotations

from datetime import date, timedelta

from domain.research.section16_features import detect_clusters, detect_streaks, eligible_open_market_rows
from providers.events.section16_models import InsiderTransaction


def _row(**overrides: object) -> InsiderTransaction:
    payload = {
        "accession_number": "0001",
        "ticker": "AAA",
        "issuer_cik": "1",
        "issuer_name": "AAA",
        "owner_cik": "101",
        "owner_name": "One",
        "owner_title": "Director",
        "is_director": True,
        "is_officer": False,
        "is_ten_percent_owner": False,
        "transaction_date": "2024-03-01",
        "filed_at": "2024-03-01",
        "transaction_code": "P",
        "acquired_disposed": "A",
        "shares": 1000.0,
        "price_per_share": 20.0,
        "value_usd": 20_000.0,
        "is_10b5_1": False,
        "is_derivative": False,
        "source": "sec_quarterly_zip",
    }
    payload.update(overrides)
    return InsiderTransaction(**payload)  # type: ignore[arg-type]


def test_eligible_rows_drop_non_open_market_derivative_and_10b51():
    rows = eligible_open_market_rows(
        [
            _row(transaction_code="P"),
            _row(accession_number="2", transaction_code="A", value_usd=1_000_000),
            _row(accession_number="3", is_derivative=True),
            _row(accession_number="4", is_10b5_1=True),
            _row(accession_number="5", transaction_code="G"),
        ]
    )
    assert len(rows) == 1
    assert rows[0].transaction_code == "P"


def test_cluster_requires_three_distinct_insiders_in_60_days():
    start = date(2024, 3, 1)
    two = [
        _row(owner_cik="101", accession_number="a", filed_at=start.isoformat()),
        _row(owner_cik="102", accession_number="b", filed_at=(start + timedelta(days=5)).isoformat()),
    ]
    assert detect_clusters(two, as_of=start + timedelta(days=10)) == []

    three = two + [
        _row(owner_cik="103", accession_number="c", filed_at=(start + timedelta(days=8)).isoformat())
    ]
    clusters = detect_clusters(three, as_of=start + timedelta(days=10))
    assert len(clusters) == 1
    assert clusters[0].insider_count == 3
    assert clusters[0].direction == "P"


def test_cluster_ignores_sub_threshold_insider_and_opposite_direction():
    start = date(2024, 3, 1)
    rows = [
        _row(owner_cik="101", accession_number="a", filed_at=start.isoformat(), value_usd=20_000),
        _row(owner_cik="102", accession_number="b", filed_at=start.isoformat(), value_usd=20_000),
        _row(owner_cik="103", accession_number="c", filed_at=start.isoformat(), value_usd=5_000),
        _row(
            owner_cik="104",
            accession_number="d",
            filed_at=start.isoformat(),
            transaction_code="S",
            acquired_disposed="D",
            value_usd=20_000,
        ),
    ]
    assert detect_clusters(rows, as_of=start) == []


def test_streak_requires_two_consecutive_weeks_and_50k():
    rows = [
        _row(filed_at="2024-03-04", accession_number="w1", value_usd=30_000),
        _row(filed_at="2024-03-12", accession_number="w2", value_usd=30_000),
    ]
    streaks = detect_streaks(rows, as_of=date(2024, 3, 15))
    assert len(streaks) == 1
    assert streaks[0].weeks == 2
    assert streaks[0].streak_value_usd == 60_000
