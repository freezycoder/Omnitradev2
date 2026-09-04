from __future__ import annotations

import pandas as pd


def compute_rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1 / window, adjust=False, min_periods=window).mean()
    relative_strength = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + relative_strength))
    rsi = rsi.fillna(50)
    rsi[(avg_loss == 0) & (avg_gain > 0)] = 100.0
    return rsi


def compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd = ema_12 - ema_26
    signal = macd.ewm(span=9, adjust=False).mean()
    histogram = macd - signal
    return macd, signal, histogram


def compute_atr(history: pd.DataFrame, window: int = 14) -> pd.Series:
    high_low = history["High"] - history["Low"]
    high_close = (history["High"] - history["Close"].shift()).abs()
    low_close = (history["Low"] - history["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.rolling(window=window, min_periods=1).mean()


def add_technical_indicators(history: pd.DataFrame) -> pd.DataFrame:
    enriched = history.copy()
    enriched["MA20"] = enriched["Close"].rolling(window=20, min_periods=1).mean()
    enriched["MA50"] = enriched["Close"].rolling(window=50, min_periods=1).mean()
    enriched["MA200"] = enriched["Close"].rolling(window=200, min_periods=1).mean()
    enriched["RSI"] = compute_rsi(enriched["Close"])

    macd, signal, histogram = compute_macd(enriched["Close"])
    enriched["MACD"] = macd
    enriched["MACD_SIGNAL"] = signal
    enriched["MACD_HIST"] = histogram
    enriched["ATR14"] = compute_atr(enriched)
    enriched["ATR_PCT"] = (enriched["ATR14"] / enriched["Close"].replace(0, pd.NA)) * 100
    return enriched
