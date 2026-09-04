from __future__ import annotations

import pandas as pd
import pytest

from providers.market import market_provider
from providers.market.market_provider import (
    apply_quote_to_latest_history,
    build_snapshot,
    fetch_earnings_estimate_context,
    fetch_price_histories,
)


def test_one_bar_snapshot_uses_quote_when_available():
    history = pd.DataFrame(
        {
            "Open": [0.0],
            "High": [0.0],
            "Low": [0.0],
            "Close": [135.0],
            "Volume": [0],
        },
        index=pd.to_datetime(["2026-06-04"]),
    )
    quote = {"c": 22.3, "d": -0.0324, "dp": -0.1451}

    adjusted = apply_quote_to_latest_history(history, quote)
    snapshot = build_snapshot(adjusted, quote=quote)

    assert adjusted["Close"].iloc[-1] == pytest.approx(22.3)
    assert adjusted["Low"].iloc[-1] == pytest.approx(22.3)
    assert snapshot is not None
    assert snapshot["current_price"] == pytest.approx(22.3)
    assert snapshot["daily_change_pct"] == pytest.approx(-0.1451)


def test_batch_price_history_splits_yfinance_multiindex(monkeypatch):
    dates = pd.bdate_range("2026-07-01", periods=3)
    columns = pd.MultiIndex.from_product(
        [["SPY", "XLK"], ["Open", "High", "Low", "Close", "Adj Close", "Volume"]]
    )
    history = pd.DataFrame(index=dates, columns=columns, dtype=float)
    for ticker, base in (("SPY", 100.0), ("XLK", 200.0)):
        history[(ticker, "Open")] = [base, base + 1, base + 2]
        history[(ticker, "High")] = [base + 1, base + 2, base + 3]
        history[(ticker, "Low")] = [base - 1, base, base + 1]
        history[(ticker, "Close")] = [base, base + 1, base + 2]
        history[(ticker, "Adj Close")] = [base, base + 1, base + 2]
        history[(ticker, "Volume")] = [1_000_000, 1_100_000, 1_200_000]

    class FakeYfinance:
        @staticmethod
        def download(**kwargs):
            assert kwargs["group_by"] == "ticker"
            return history

    monkeypatch.setattr(market_provider, "_yf", lambda: FakeYfinance)

    result = fetch_price_histories(["SPY", "XLK"])

    assert set(result) == {"SPY", "XLK"}
    assert list(result["SPY"].columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert result["XLK"]["Close"].iloc[-1] == pytest.approx(202.0)


def test_earnings_estimate_context_normalizes_calendar_consensus_and_revisions(monkeypatch):
    class FakeTicker:
        calendar = {"Earnings Date": [pd.Timestamp("2026-07-30")]}
        earnings_estimate = pd.DataFrame(
            {
                "avg": [1.89138],
                "low": [1.82],
                "high": [1.99],
                "yearAgoEps": [1.57],
                "numberOfAnalysts": [31],
                "growth": [0.2047],
            },
            index=["0q"],
        )
        eps_revisions = pd.DataFrame(
            {
                "upLast7days": [0],
                "upLast30days": [24],
                "downLast30days": [0],
                "downLast7Days": [0],
            },
            index=["0q"],
        )

    class FakeYfinance:
        @staticmethod
        def Ticker(ticker):
            assert ticker == "AAPL"
            return FakeTicker()

    monkeypatch.setattr(market_provider, "_yf", lambda: FakeYfinance)

    result = fetch_earnings_estimate_context("AAPL")

    assert result["status"] == "available"
    assert result["next_earnings_date"] == "2026-07-30"
    assert result["current_quarter"]["growth_pct"] == pytest.approx(20.47)
    assert result["current_quarter"]["analyst_count"] == 31
    assert result["revisions"]["up_30d"] == 24
