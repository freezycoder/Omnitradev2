from __future__ import annotations

from dataclasses import dataclass


def _dedupe(tickers: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for ticker in tickers:
        normalized = ticker.upper().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


US_STOCK_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "AVGO",
    "AMD",
    "NFLX",
    "ORCL",
    "CRM",
    "JPM",
    "V",
    "LLY",
    "ABBV",
    "UNH",
    "XOM",
    "COST",
    "WMT",
    "UBER",
]

EMERGING_STOCK_UNIVERSE = [
    "SPCX",
    "PSKY",
    "SNDK",
    "QBTS",
    "BE",
]

INTERNATIONAL_STOCK_UNIVERSE = [
    "TSM",
    "ASML",
    "NVO",
    "SHEL",
    "SAP",
    "BABA",
    "SONY",
    "TM",
    "RY",
    "SHOP",
    "MELI",
    "PDD",
    "UL",
    "RELX",
]

DEFAULT_STOCK_UNIVERSE = _dedupe(US_STOCK_UNIVERSE + INTERNATIONAL_STOCK_UNIVERSE + EMERGING_STOCK_UNIVERSE)


@dataclass(frozen=True)
class UniverseFilters:
    min_price: float = 10.0
    min_average_volume: float = 2_000_000
    min_market_cap: float = 10_000_000_000
    min_history_points: int = 180


SCAN_UNIVERSE_FILTERS = UniverseFilters()
EMERGING_UNIVERSE_FILTERS = UniverseFilters(
    min_price=1.0,
    min_average_volume=0.0,
    min_market_cap=0.0,
    min_history_points=1,
)
DEFAULT_UNIVERSE_NAME = "Global Liquid Leaders"
INTERNATIONAL_UNIVERSE_NAME = "International Large Caps"
EMERGING_UNIVERSE_NAME = "Emerging Watchlist"


def universe_filters_for_ticker(ticker: str) -> UniverseFilters:
    normalized = ticker.upper().strip()
    if normalized in EMERGING_STOCK_UNIVERSE:
        return EMERGING_UNIVERSE_FILTERS
    return SCAN_UNIVERSE_FILTERS

UNIVERSE_REGISTRY = {
    "global": {
        "name": DEFAULT_UNIVERSE_NAME,
        "tickers": DEFAULT_STOCK_UNIVERSE,
    },
    "international": {
        "name": INTERNATIONAL_UNIVERSE_NAME,
        "tickers": INTERNATIONAL_STOCK_UNIVERSE,
    },
    "emerging": {
        "name": EMERGING_UNIVERSE_NAME,
        "tickers": EMERGING_STOCK_UNIVERSE,
    },
}
