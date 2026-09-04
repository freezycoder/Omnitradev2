from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from domain.technical.indicators import (
    add_technical_indicators,
    compute_atr,
    compute_macd,
    compute_rsi,
)


def _flat_close(n: int = 50, price: float = 100.0) -> pd.Series:
    return pd.Series([price] * n, dtype=float)


def _rising_close(n: int = 50, start: float = 80.0, end: float = 150.0) -> pd.Series:
    return pd.Series(np.linspace(start, end, n), dtype=float)


def _falling_close(n: int = 50, start: float = 150.0, end: float = 80.0) -> pd.Series:
    return pd.Series(np.linspace(start, end, n), dtype=float)


def _oscillating_rising_close(n: int = 60) -> pd.Series:
    """Up 3, down 1 zigzag that trends strongly upward — avg_gain >> avg_loss."""
    prices = [100.0]
    for i in range(1, n):
        prices.append(prices[-1] + (3.0 if i % 4 != 0 else -1.0))
    return pd.Series(prices, dtype=float)


def _make_ohlcv(n: int = 60, price: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({
        "Open": [price] * n,
        "High": [price + 1] * n,
        "Low": [price - 1] * n,
        "Close": [price] * n,
        "Volume": [1_000_000] * n,
    })


class TestComputeRsi:
    def test_flat_series_returns_50(self):
        rsi = compute_rsi(_flat_close())
        assert rsi.iloc[-1] == pytest.approx(50.0)

    def test_rsi_bounded_0_to_100(self):
        for close in (_flat_close(), _rising_close(), _falling_close()):
            rsi = compute_rsi(close)
            assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_strongly_rising_gives_high_rsi(self):
        rsi = compute_rsi(_oscillating_rising_close(n=60))
        assert rsi.iloc[-1] > 65

    def test_strongly_falling_gives_low_rsi(self):
        rsi = compute_rsi(_falling_close(n=60))
        assert rsi.iloc[-1] < 40

    def test_returns_series_same_length(self):
        close = _flat_close(n=30)
        assert len(compute_rsi(close)) == 30

    def test_no_nans_in_output(self):
        rsi = compute_rsi(_rising_close(n=40))
        assert not rsi.isna().any()

    def test_custom_window(self):
        # Use oscillating-rising series so avg_loss > 0 and window comparison is meaningful
        rsi_14 = compute_rsi(_oscillating_rising_close(), window=14)
        rsi_7 = compute_rsi(_oscillating_rising_close(), window=7)
        assert rsi_7.iloc[-1] > rsi_14.iloc[-1]


class TestComputeMacd:
    def test_returns_three_series(self):
        macd, signal, histogram = compute_macd(_rising_close(n=60))
        assert len(macd) == len(signal) == len(histogram) == 60

    def test_histogram_equals_macd_minus_signal(self):
        macd, signal, histogram = compute_macd(_rising_close(n=60))
        pd.testing.assert_series_equal(histogram, macd - signal)

    def test_rising_trend_macd_positive(self):
        macd, _, _ = compute_macd(_rising_close(n=60))
        assert macd.iloc[-1] > 0

    def test_falling_trend_macd_negative(self):
        macd, _, _ = compute_macd(_falling_close(n=60))
        assert macd.iloc[-1] < 0


class TestComputeAtr:
    def test_non_negative(self):
        df = _make_ohlcv()
        atr = compute_atr(df)
        assert (atr >= 0).all()

    def test_constant_high_low_gives_stable_atr(self):
        df = _make_ohlcv(n=30, price=100.0)
        atr = compute_atr(df)
        assert atr.iloc[-1] == pytest.approx(2.0, rel=0.05)


class TestAddTechnicalIndicators:
    def test_adds_all_required_columns(self):
        required = {"MA20", "MA50", "MA200", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST", "ATR14", "ATR_PCT"}
        enriched = add_technical_indicators(_make_ohlcv(n=220))
        assert required.issubset(set(enriched.columns))

    def test_does_not_mutate_input(self):
        df = _make_ohlcv(n=50)
        original_cols = set(df.columns)
        add_technical_indicators(df)
        assert set(df.columns) == original_cols

    def test_ma200_converges_on_flat_price(self):
        df = _make_ohlcv(n=220, price=50.0)
        enriched = add_technical_indicators(df)
        assert enriched["MA200"].iloc[-1] == pytest.approx(50.0)

    def test_atr_pct_bounded_reasonably(self):
        df = _make_ohlcv(n=50, price=100.0)
        enriched = add_technical_indicators(df)
        assert enriched["ATR_PCT"].iloc[-1] < 10
