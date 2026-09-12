from __future__ import annotations

import pytest

from domain.etf.models import EtfHolding
from domain.etf.overlap import pairwise_overlap, shared_and_unique


def _holding(etf: str, ticker: str, weight: float) -> EtfHolding:
    return EtfHolding(etf_ticker=etf, holding_ticker=ticker, holding_name=ticker, weight=weight)


def test_pairwise_overlap_uses_min_weights():
    etf_a = [
        _holding("AAA", "AAPL", 0.10),
        _holding("AAA", "MSFT", 0.20),
    ]
    etf_b = [
        _holding("BBB", "AAPL", 0.05),
        _holding("BBB", "MSFT", 0.10),
    ]

    overlap = pairwise_overlap(etf_a, etf_b)

    assert overlap == pytest.approx(0.15)


def test_shared_and_unique_holdings_split_correctly():
    etf_a = [_holding("AAA", "AAPL", 0.10), _holding("AAA", "NVDA", 0.08)]
    etf_b = [_holding("BBB", "AAPL", 0.05), _holding("BBB", "MSFT", 0.12)]

    shared, unique_a, unique_b = shared_and_unique(etf_a, etf_b)

    assert [item.ticker for item in shared] == ["AAPL"]
    assert unique_a[0].ticker == "NVDA"
    assert unique_b[0].ticker == "MSFT"
