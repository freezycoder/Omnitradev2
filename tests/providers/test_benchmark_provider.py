from __future__ import annotations

import pandas as pd

from providers.market import benchmark_provider


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [101.0, 102.0],
            "Low": [99.0, 100.0],
            "Close": [100.0, 101.0],
            "Volume": [1_000_000, 1_000_000],
        },
        index=pd.bdate_range("2026-07-01", periods=2),
    )


def test_sector_mapping_matches_yfinance_sector_labels():
    assert benchmark_provider.sector_etf_for_sector("Technology") == "XLK"
    assert benchmark_provider.sector_etf_for_sector("Financial Services") == "XLF"
    assert benchmark_provider.sector_etf_for_sector("Unknown") is None


def test_benchmark_histories_are_cached(monkeypatch):
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(benchmark_provider, "_CACHE", {})

    def fake_batch(symbols, period: str):
        calls.append(tuple(symbols))
        assert period == "2y"
        return {symbol: _history() for symbol in symbols}

    monkeypatch.setattr(benchmark_provider, "fetch_price_histories", fake_batch)

    first = benchmark_provider.load_relative_strength_benchmarks("Technology")
    second = benchmark_provider.load_relative_strength_benchmarks("Technology")

    assert first.status == "available"
    assert second.status == "available"
    assert len(calls) == 1
    assert "SPY" in calls[0]
    assert "XLK" in calls[0]
