from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import pandas as pd

from providers.market.market_provider import fetch_price_histories, fetch_price_history


_log = logging.getLogger(__name__)
MARKET_BENCHMARK_SYMBOL = "SPY"
BENCHMARK_CACHE_TTL_SECONDS = 6 * 60 * 60

SECTOR_ETF_BY_SECTOR = {
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Real Estate": "XLRE",
    "Technology": "XLK",
    "Utilities": "XLU",
}

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_LOCK = threading.Lock()
_FETCH_LOCK = threading.Lock()
_REFERENCE_SYMBOLS = tuple(dict.fromkeys((MARKET_BENCHMARK_SYMBOL, *SECTOR_ETF_BY_SECTOR.values())))


@dataclass(frozen=True)
class BenchmarkBundle:
    market_symbol: str
    sector_symbol: str | None
    market_history: pd.DataFrame
    sector_history: pd.DataFrame
    status: str
    message: str | None = None


def sector_etf_for_sector(sector: str) -> str | None:
    return SECTOR_ETF_BY_SECTOR.get(str(sector or "").strip())


def _cached_history(symbol: str) -> pd.DataFrame | None:
    with _CACHE_LOCK:
        cached = _CACHE.get(symbol)
        if cached is None or time.monotonic() - cached[0] > BENCHMARK_CACHE_TTL_SECONDS:
            return None
        return cached[1].copy()


def _load_history(symbol: str) -> pd.DataFrame:
    cached = _cached_history(symbol)
    if cached is not None:
        return cached

    with _FETCH_LOCK:
        cached = _cached_history(symbol)
        if cached is not None:
            return cached
        missing_symbols = [
            reference_symbol
            for reference_symbol in _REFERENCE_SYMBOLS
            if _cached_history(reference_symbol) is None
        ]
        try:
            histories = fetch_price_histories(missing_symbols, period="2y")
        except Exception:
            _log.warning("Relative-strength benchmark batch was unavailable.", exc_info=True)
            histories = {}
        with _CACHE_LOCK:
            cached_at = time.monotonic()
            for reference_symbol in missing_symbols:
                _CACHE[reference_symbol] = (
                    cached_at,
                    histories.get(reference_symbol, pd.DataFrame()).copy(),
                )
        history = _cached_history(symbol)
        if history is not None and not history.empty:
            return history

        try:
            history = fetch_price_history(symbol, period="2y")
        except Exception:
            _log.warning("Relative-strength benchmark %s was unavailable.", symbol, exc_info=True)
            history = pd.DataFrame()
        with _CACHE_LOCK:
            _CACHE[symbol] = (time.monotonic(), history.copy())
        return history.copy()


def load_relative_strength_benchmarks(sector: str) -> BenchmarkBundle:
    sector_symbol = sector_etf_for_sector(sector)
    market_history = _load_history(MARKET_BENCHMARK_SYMBOL)
    sector_history = _load_history(sector_symbol) if sector_symbol else pd.DataFrame()

    if market_history.empty:
        return BenchmarkBundle(
            market_symbol=MARKET_BENCHMARK_SYMBOL,
            sector_symbol=sector_symbol,
            market_history=market_history,
            sector_history=sector_history,
            status="unavailable",
            message=f"{MARKET_BENCHMARK_SYMBOL} history was unavailable.",
        )
    if sector_symbol is None:
        return BenchmarkBundle(
            market_symbol=MARKET_BENCHMARK_SYMBOL,
            sector_symbol=None,
            market_history=market_history,
            sector_history=sector_history,
            status="partial",
            message=f"No sector ETF mapping is configured for {sector or 'this company'}.",
        )
    if sector_history.empty:
        return BenchmarkBundle(
            market_symbol=MARKET_BENCHMARK_SYMBOL,
            sector_symbol=sector_symbol,
            market_history=market_history,
            sector_history=sector_history,
            status="partial",
            message=f"{sector_symbol} history was unavailable.",
        )
    return BenchmarkBundle(
        market_symbol=MARKET_BENCHMARK_SYMBOL,
        sector_symbol=sector_symbol,
        market_history=market_history,
        sector_history=sector_history,
        status="available",
    )


__all__ = [
    "BENCHMARK_CACHE_TTL_SECONDS",
    "MARKET_BENCHMARK_SYMBOL",
    "SECTOR_ETF_BY_SECTOR",
    "BenchmarkBundle",
    "load_relative_strength_benchmarks",
    "sector_etf_for_sector",
]
