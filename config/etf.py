from __future__ import annotations

from dataclasses import dataclass


ETF_CACHE_TTL_HOURS = 24
ETF_HOLDINGS_CACHE_TTL_HOURS = 24
ETF_SCREENER_CACHE_KEY = "etf"
MIN_ETF_EXPOSURE_WEIGHT = 0.005
MIN_OVERLAP_HOLDING_WEIGHT = 0.0
ETF_SCREENER_PAGE_SIZE = 50
MIN_BARS_FOR_VOLATILITY = 20
MIN_BARS_FOR_SHARPE = 60
MIN_BARS_FOR_DOWNSIDE = 60
MIN_BARS_FOR_1Y = 200
MIN_BARS_FOR_3Y = 600
MIN_BARS_FOR_5Y = 1000


US_EQUITY_ETFS = [
    "SPY",
    "VOO",
    "IVV",
    "VTI",
    "QQQ",
    "IWM",
    "DIA",
]

SECTOR_ETFS = [
    "XLK",
    "XLF",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
]

INTERNATIONAL_ETFS = [
    "EFA",
    "EEM",
    "VEA",
    "VWO",
    "IEMG",
]

FIXED_INCOME_ETFS = [
    "AGG",
    "BND",
    "TLT",
    "IEF",
    "LQD",
    "HYG",
]

COMMODITY_ETFS = [
    "GLD",
    "SLV",
    "USO",
    "DBC",
]

THEMATIC_STYLE_ETFS = [
    "SMH",
    "XBI",
    "ARKK",
    "IWF",
    "IWD",
    "MTUM",
    "QUAL",
    "USMV",
]


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


DEFAULT_ETF_UNIVERSE = _dedupe(
    US_EQUITY_ETFS
    + SECTOR_ETFS
    + INTERNATIONAL_ETFS
    + FIXED_INCOME_ETFS
    + COMMODITY_ETFS
    + THEMATIC_STYLE_ETFS
)

ETF_UNIVERSE_NAME = "Liquid US-listed ETFs"


@dataclass(frozen=True)
class EtfOmniScoreWeights:
    momentum: float = 0.30
    risk: float = 0.20
    liquidity: float = 0.15
    fund_quality: float = 0.20
    flows: float = 0.05
    underlying_exposure: float = 0.10


ETF_OMNISCORE_WEIGHTS = EtfOmniScoreWeights()


@dataclass(frozen=True)
class EtfUniverseFilters:
    ticker: str | None = None
    name: str | None = None
    issuer: str | None = None
    asset_class: str | None = None
    category: str | None = None
    sector: str | None = None
    geography: str | None = None
    max_expense_ratio: float | None = None
    min_aum: float | None = None
    min_average_volume: float | None = None
    min_dividend_yield: float | None = None


__all__ = [
    "COMMODITY_ETFS",
    "DEFAULT_ETF_UNIVERSE",
    "ETF_CACHE_TTL_HOURS",
    "ETF_HOLDINGS_CACHE_TTL_HOURS",
    "ETF_OMNISCORE_WEIGHTS",
    "ETF_SCREENER_CACHE_KEY",
    "ETF_SCREENER_PAGE_SIZE",
    "ETF_UNIVERSE_NAME",
    "EtfOmniScoreWeights",
    "EtfUniverseFilters",
    "FIXED_INCOME_ETFS",
    "INTERNATIONAL_ETFS",
    "MIN_BARS_FOR_1Y",
    "MIN_BARS_FOR_3Y",
    "MIN_BARS_FOR_5Y",
    "MIN_BARS_FOR_DOWNSIDE",
    "MIN_BARS_FOR_SHARPE",
    "MIN_BARS_FOR_VOLATILITY",
    "MIN_ETF_EXPOSURE_WEIGHT",
    "MIN_OVERLAP_HOLDING_WEIGHT",
    "SECTOR_ETFS",
    "THEMATIC_STYLE_ETFS",
    "US_EQUITY_ETFS",
]
