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

DEFAULT_ETF_REGION = "us"

ETF_REGION_ALIASES = {
    "usa": "us",
    "united_states": "us",
    "unitedstates": "us",
    "eu": "europe",
    "eea": "europe",
    "uk": "europe",
    "ucits": "europe",
    "apac": "asia_pacific",
    "asia": "asia_pacific",
    "asia_pac": "asia_pacific",
    "asiapacific": "asia_pacific",
    "jp": "asia_pacific",
    "hk": "asia_pacific",
    "au": "asia_pacific",
}


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

# UCITS / Europe-listed funds for EU/EEA and UK retail accounts that cannot
# buy the US-listed share classes above (PRIIPs / KID). Tickers are yfinance
# exchange suffixes: .DE Xetra, .L London, .AS Amsterdam.
EUROPE_WORLD_ETFS = [
    "VWCE.DE",
    "VWRA.L",
    "VWRL.L",
    "EUNL.DE",
    "IWDA.AS",
    "SWDA.L",
    "IUSQ.DE",
    "XDWD.DE",
]

EUROPE_US_ETFS = [
    "SXR8.DE",
    "CSPX.L",
    "VUAA.L",
    "VUSA.L",
    "SPY5.DE",
    "SXRV.DE",
    "EQQQ.L",
]

EUROPE_REGIONAL_ETFS = [
    "EXW1.DE",
    "EXS1.DE",
    "EXSA.DE",
    "IMAE.AS",
    "ISF.L",
    "IS3N.DE",
    "EIMI.L",
    "VFEM.L",
    "EMIM.L",
]

EUROPE_BOND_COMMODITY_ETFS = [
    "AGGU.L",
    "IEAC.L",
    "VAGF.DE",
    "SGLN.L",
    "4GLD.DE",
    "XEON.DE",
]

EUROPE_THEMATIC_STYLE_ETFS = [
    "XAIX.DE",
    "IUIT.L",
    "INRG.L",
    "IUSN.DE",
    "ZPRV.DE",
    "ZPRX.DE",
]

ASIA_PACIFIC_JAPAN_ETFS = [
    "1306.T",
    "1321.T",
    "1348.T",
    "1578.T",
    "1655.T",
    "2558.T",
    "2631.T",
]

ASIA_PACIFIC_HK_ETFS = [
    "2800.HK",
    "2823.HK",
    "2828.HK",
    "3033.HK",
    "3188.HK",
]

ASIA_PACIFIC_AU_ETFS = [
    "STW.AX",
    "VAS.AX",
    "VGS.AX",
    "VTS.AX",
    "IVV.AX",
    "NDQ.AX",
    "A200.AX",
    "IOZ.AX",
    "IEM.AX",
    "GOLD.AX",
    "QUAL.AX",
    "ETHI.AX",
    "BGBL.AX",
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


@dataclass(frozen=True)
class EtfListingRegion:
    key: str
    label: str
    short_label: str
    description: str
    universe_name: str


ETF_REGIONS: tuple[EtfListingRegion, ...] = (
    EtfListingRegion(
        key="us",
        label="United States",
        short_label="US",
        description="US-listed ETFs for US brokerage accounts. EU/EEA retail accounts typically cannot buy these share classes.",
        universe_name="Liquid US-listed ETFs",
    ),
    EtfListingRegion(
        key="europe",
        label="Europe (UCITS)",
        short_label="Europe",
        description="UCITS ETFs listed on Xetra, London, and Euronext Amsterdam for EU/EEA and UK retail accounts.",
        universe_name="Liquid Europe-listed UCITS ETFs",
    ),
    EtfListingRegion(
        key="asia_pacific",
        label="Asia-Pacific",
        short_label="Asia-Pacific",
        description="ETFs listed in Tokyo, Hong Kong, and Australia.",
        universe_name="Liquid Asia-Pacific listed ETFs",
    ),
)

ETF_UNIVERSES: dict[str, list[str]] = {
    "us": _dedupe(
        US_EQUITY_ETFS
        + SECTOR_ETFS
        + INTERNATIONAL_ETFS
        + FIXED_INCOME_ETFS
        + COMMODITY_ETFS
        + THEMATIC_STYLE_ETFS
    ),
    "europe": _dedupe(
        EUROPE_WORLD_ETFS
        + EUROPE_US_ETFS
        + EUROPE_REGIONAL_ETFS
        + EUROPE_BOND_COMMODITY_ETFS
        + EUROPE_THEMATIC_STYLE_ETFS
    ),
    "asia_pacific": _dedupe(
        ASIA_PACIFIC_JAPAN_ETFS
        + ASIA_PACIFIC_HK_ETFS
        + ASIA_PACIFIC_AU_ETFS
    ),
}

DEFAULT_ETF_UNIVERSE = ETF_UNIVERSES[DEFAULT_ETF_REGION]
ETF_UNIVERSE_NAME = ETF_REGIONS[0].universe_name
ALL_ETF_TICKERS = tuple(_dedupe([ticker for universe in ETF_UNIVERSES.values() for ticker in universe]))
ALL_ETF_TICKER_SET = frozenset(ALL_ETF_TICKERS)


def normalize_etf_region(value: str | None) -> str:
    key = (value or DEFAULT_ETF_REGION).strip().lower().replace("-", "_").replace(" ", "_")
    key = ETF_REGION_ALIASES.get(key, key)
    if key not in ETF_UNIVERSES:
        return DEFAULT_ETF_REGION
    return key


def universe_for(region: str | None = None) -> list[str]:
    return list(ETF_UNIVERSES[normalize_etf_region(region)])


def universe_name_for(region: str | None = None) -> str:
    normalized = normalize_etf_region(region)
    for item in ETF_REGIONS:
        if item.key == normalized:
            return item.universe_name
    return ETF_UNIVERSE_NAME


def cache_key_for_region(region: str | None = None) -> str:
    return f"etf_{normalize_etf_region(region)}"


def cache_keys_for_region(region: str | None = None) -> tuple[str, ...]:
    primary = cache_key_for_region(region)
    if normalize_etf_region(region) == DEFAULT_ETF_REGION:
        return (primary, ETF_SCREENER_CACHE_KEY)
    return (primary,)


def listing_regions_payload() -> list[dict[str, object]]:
    return [
        {
            "key": item.key,
            "label": item.label,
            "short_label": item.short_label,
            "description": item.description,
            "universe_name": item.universe_name,
            "ticker_count": len(ETF_UNIVERSES[item.key]),
        }
        for item in ETF_REGIONS
    ]


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
    "ALL_ETF_TICKERS",
    "ALL_ETF_TICKER_SET",
    "ASIA_PACIFIC_AU_ETFS",
    "ASIA_PACIFIC_HK_ETFS",
    "ASIA_PACIFIC_JAPAN_ETFS",
    "COMMODITY_ETFS",
    "DEFAULT_ETF_REGION",
    "DEFAULT_ETF_UNIVERSE",
    "ETF_CACHE_TTL_HOURS",
    "ETF_HOLDINGS_CACHE_TTL_HOURS",
    "ETF_OMNISCORE_WEIGHTS",
    "ETF_REGION_ALIASES",
    "ETF_REGIONS",
    "ETF_SCREENER_CACHE_KEY",
    "ETF_SCREENER_PAGE_SIZE",
    "ETF_UNIVERSES",
    "ETF_UNIVERSE_NAME",
    "EUROPE_BOND_COMMODITY_ETFS",
    "EUROPE_REGIONAL_ETFS",
    "EUROPE_THEMATIC_STYLE_ETFS",
    "EUROPE_US_ETFS",
    "EUROPE_WORLD_ETFS",
    "EtfListingRegion",
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
    "cache_key_for_region",
    "cache_keys_for_region",
    "listing_regions_payload",
    "normalize_etf_region",
    "universe_for",
    "universe_name_for",
]
