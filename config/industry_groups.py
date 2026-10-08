from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from config.universe import DEFAULT_STOCK_UNIVERSE


INDUSTRY_GROUP_MAP_VERSION = "gics-subindustry-proxy-v1"
INDUSTRY_GROUP_TAXONOMY = "gics_subindustry_proxy"
INDUSTRY_GROUP_MAP_FROZEN_ON = "2026-09-14"
MIN_LIQUID_UNIVERSE_COVERAGE = 0.80

# IBD's ~197 industry groups are not a public, redistributable membership file.
# This freeze uses GICS sub-industry (MSCI/S&P, 8-digit) as the nearest public
# proxy and must be labeled as a proxy in every shadow payload. Do not treat
# lift on this map as evidence for IBD's proprietary 197-group taxonomy.
INDUSTRY_GROUP_SOURCE = (
    "GICS sub-industry proxy for the OmniTrade liquid universe. "
    "IBD ~197 industry groups are proprietary and are not used. "
    "Membership is frozen at map version gics-subindustry-proxy-v1."
)


@dataclass(frozen=True)
class IndustryGroupMembership:
    ticker: str
    group_id: str
    group_name: str
    gics_code: str
    gics_industry_group: str
    sector: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _membership(
    ticker: str,
    gics_code: str,
    group_name: str,
    gics_industry_group: str,
    sector: str,
) -> IndustryGroupMembership:
    return IndustryGroupMembership(
        ticker=ticker,
        group_id=f"gics-{gics_code}",
        group_name=group_name,
        gics_code=gics_code,
        gics_industry_group=gics_industry_group,
        sector=sector,
    )


# Frozen ticker → GICS sub-industry membership for DEFAULT_STOCK_UNIVERSE.
# Codes follow the public GICS structure (sector / industry group / industry /
# sub-industry). Names are the GICS sub-industry labels.
_INDUSTRY_GROUP_ROWS: tuple[IndustryGroupMembership, ...] = (
    _membership("AAPL", "45202020", "Technology Hardware, Storage & Peripherals", "Technology Hardware & Equipment", "Information Technology"),
    _membership("MSFT", "45103020", "Systems Software", "Software & Services", "Information Technology"),
    _membership("NVDA", "45301020", "Semiconductors", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("AMZN", "25503030", "Broadline Retail", "Consumer Discretionary Distribution & Retail", "Consumer Discretionary"),
    _membership("GOOGL", "50203010", "Interactive Media & Services", "Media & Entertainment", "Communication Services"),
    _membership("META", "50203010", "Interactive Media & Services", "Media & Entertainment", "Communication Services"),
    _membership("AVGO", "45301020", "Semiconductors", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("AMD", "45301020", "Semiconductors", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("NFLX", "50202010", "Movies & Entertainment", "Media & Entertainment", "Communication Services"),
    _membership("ORCL", "45103020", "Systems Software", "Software & Services", "Information Technology"),
    _membership("CRM", "45103010", "Application Software", "Software & Services", "Information Technology"),
    _membership("JPM", "40101010", "Diversified Banks", "Banks", "Financials"),
    _membership("V", "40201040", "Transaction & Payment Processing Services", "Financial Services", "Financials"),
    _membership("LLY", "35202010", "Pharmaceuticals", "Pharmaceuticals, Biotechnology & Life Sciences", "Health Care"),
    _membership("ABBV", "35202010", "Pharmaceuticals", "Pharmaceuticals, Biotechnology & Life Sciences", "Health Care"),
    _membership("UNH", "35102030", "Managed Health Care", "Health Care Equipment & Services", "Health Care"),
    _membership("XOM", "10102010", "Integrated Oil & Gas", "Energy", "Energy"),
    _membership("COST", "30101040", "Consumer Staples Merchandise Retail", "Consumer Staples Distribution & Retail", "Consumer Staples"),
    _membership("WMT", "30101040", "Consumer Staples Merchandise Retail", "Consumer Staples Distribution & Retail", "Consumer Staples"),
    _membership("UBER", "20304040", "Passenger Ground Transportation", "Transportation", "Industrials"),
    _membership("TSM", "45301020", "Semiconductors", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("ASML", "45301010", "Semiconductor Materials & Equipment", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("NVO", "35202010", "Pharmaceuticals", "Pharmaceuticals, Biotechnology & Life Sciences", "Health Care"),
    _membership("SHEL", "10102010", "Integrated Oil & Gas", "Energy", "Energy"),
    _membership("SAP", "45103010", "Application Software", "Software & Services", "Information Technology"),
    _membership("BABA", "25503030", "Broadline Retail", "Consumer Discretionary Distribution & Retail", "Consumer Discretionary"),
    _membership("SONY", "45203010", "Consumer Electronics", "Technology Hardware & Equipment", "Information Technology"),
    _membership("TM", "25102010", "Automobile Manufacturers", "Automobiles & Components", "Consumer Discretionary"),
    _membership("RY", "40101010", "Diversified Banks", "Banks", "Financials"),
    _membership("SHOP", "45103010", "Application Software", "Software & Services", "Information Technology"),
    _membership("MELI", "25503030", "Broadline Retail", "Consumer Discretionary Distribution & Retail", "Consumer Discretionary"),
    _membership("PDD", "25503030", "Broadline Retail", "Consumer Discretionary Distribution & Retail", "Consumer Discretionary"),
    _membership("UL", "30302010", "Personal Care Products", "Household & Personal Products", "Consumer Staples"),
    _membership("RELX", "20202020", "Research & Consulting Services", "Commercial & Professional Services", "Industrials"),
    _membership("SPCX", "40201030", "Multi-Sector Holdings", "Financial Services", "Financials"),
    _membership("PSKY", "50202010", "Movies & Entertainment", "Media & Entertainment", "Communication Services"),
    _membership("SNDK", "45301020", "Semiconductors", "Semiconductors & Semiconductor Equipment", "Information Technology"),
    _membership("QBTS", "45203020", "Electronic Equipment & Instruments", "Technology Hardware & Equipment", "Information Technology"),
    _membership("BE", "20104020", "Heavy Electrical Equipment", "Capital Goods", "Industrials"),
)

INDUSTRY_GROUP_MAP: dict[str, IndustryGroupMembership] = {
    row.ticker: row for row in _INDUSTRY_GROUP_ROWS
}


def normalize_ticker(ticker: str) -> str:
    return str(ticker or "").upper().strip()


def industry_group_for_ticker(
    ticker: str,
    mapping: Mapping[str, IndustryGroupMembership] | None = None,
) -> IndustryGroupMembership | None:
    catalog = mapping if mapping is not None else INDUSTRY_GROUP_MAP
    return catalog.get(normalize_ticker(ticker))


def mapped_tickers(mapping: Mapping[str, IndustryGroupMembership] | None = None) -> tuple[str, ...]:
    catalog = mapping if mapping is not None else INDUSTRY_GROUP_MAP
    return tuple(sorted(catalog))


def universe_coverage(
    universe: list[str] | tuple[str, ...] | None = None,
    mapping: Mapping[str, IndustryGroupMembership] | None = None,
) -> dict[str, Any]:
    catalog = mapping if mapping is not None else INDUSTRY_GROUP_MAP
    tickers = [normalize_ticker(ticker) for ticker in (universe or DEFAULT_STOCK_UNIVERSE)]
    tickers = list(dict.fromkeys(ticker for ticker in tickers if ticker))
    mapped = [ticker for ticker in tickers if ticker in catalog]
    unmapped = [ticker for ticker in tickers if ticker not in catalog]
    coverage = (len(mapped) / len(tickers)) if tickers else 0.0
    return {
        "map_version": INDUSTRY_GROUP_MAP_VERSION,
        "taxonomy": INDUSTRY_GROUP_TAXONOMY,
        "frozen_on": INDUSTRY_GROUP_MAP_FROZEN_ON,
        "source": INDUSTRY_GROUP_SOURCE,
        "universe_size": len(tickers),
        "mapped_count": len(mapped),
        "unmapped_tickers": unmapped,
        "coverage": round(coverage, 4),
        "coverage_pct": round(coverage * 100.0, 2),
        "meets_minimum_coverage": coverage >= MIN_LIQUID_UNIVERSE_COVERAGE,
        "minimum_coverage": MIN_LIQUID_UNIVERSE_COVERAGE,
    }


def map_manifest() -> dict[str, Any]:
    groups = sorted({row.group_id for row in INDUSTRY_GROUP_MAP.values()})
    return {
        "map_version": INDUSTRY_GROUP_MAP_VERSION,
        "taxonomy": INDUSTRY_GROUP_TAXONOMY,
        "frozen_on": INDUSTRY_GROUP_MAP_FROZEN_ON,
        "source": INDUSTRY_GROUP_SOURCE,
        "group_count": len(groups),
        "mapped_ticker_count": len(INDUSTRY_GROUP_MAP),
        "is_ibd_197": False,
        "proxy_label": "gics_subindustry_proxy_not_ibd_197",
    }


__all__ = [
    "INDUSTRY_GROUP_MAP",
    "INDUSTRY_GROUP_MAP_FROZEN_ON",
    "INDUSTRY_GROUP_MAP_VERSION",
    "INDUSTRY_GROUP_SOURCE",
    "INDUSTRY_GROUP_TAXONOMY",
    "IndustryGroupMembership",
    "MIN_LIQUID_UNIVERSE_COVERAGE",
    "industry_group_for_ticker",
    "map_manifest",
    "mapped_tickers",
    "normalize_ticker",
    "universe_coverage",
]
