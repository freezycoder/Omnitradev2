from pathlib import Path
import re

from config.etf import (
    ALL_ETF_TICKERS,
    DEFAULT_ETF_REGION,
    DEFAULT_ETF_UNIVERSE,
    ETF_OMNISCORE_WEIGHTS,
    ETF_SCREENER_CACHE_KEY,
    ETF_UNIVERSES,
    cache_key_for_region,
    cache_keys_for_region,
    listing_regions_payload,
    normalize_etf_region,
    universe_for,
    universe_name_for,
)
import pytest


def test_etf_universe_is_deduped_and_includes_core_liquid_funds():
    assert "QQQ" in DEFAULT_ETF_UNIVERSE
    assert "SPY" in DEFAULT_ETF_UNIVERSE
    assert "SMH" in DEFAULT_ETF_UNIVERSE
    assert len(DEFAULT_ETF_UNIVERSE) == len(set(DEFAULT_ETF_UNIVERSE))


def test_omniscore_weights_are_positive():
    total = (
        ETF_OMNISCORE_WEIGHTS.momentum
        + ETF_OMNISCORE_WEIGHTS.risk
        + ETF_OMNISCORE_WEIGHTS.liquidity
        + ETF_OMNISCORE_WEIGHTS.fund_quality
        + ETF_OMNISCORE_WEIGHTS.flows
        + ETF_OMNISCORE_WEIGHTS.underlying_exposure
    )
    assert total == pytest.approx(1.0)


def test_listing_regions_cover_us_europe_and_asia_pacific():
    keys = {item["key"] for item in listing_regions_payload()}
    assert keys == {"us", "europe", "asia_pacific"}
    assert DEFAULT_ETF_REGION == "us"
    assert universe_for("us") == DEFAULT_ETF_UNIVERSE
    assert "SPY" in universe_for("us")
    assert "SPY" not in universe_for("europe")
    assert "VWCE.DE" in universe_for("europe")
    assert "VWCE.DE" not in universe_for("us")
    assert "2800.HK" in universe_for("asia_pacific")
    assert "1306.T" in universe_for("asia_pacific")
    assert "VAS.AX" in universe_for("asia_pacific")


def test_region_aliases_and_invalid_values_normalize():
    assert normalize_etf_region("EU") == "europe"
    assert normalize_etf_region("ucits") == "europe"
    assert normalize_etf_region("asia-pacific") == "asia_pacific"
    assert normalize_etf_region("not-a-region") == "us"
    assert normalize_etf_region(None) == "us"


def test_cache_keys_are_isolated_and_us_keeps_legacy_fallback():
    assert cache_key_for_region("europe") == "etf_europe"
    assert cache_key_for_region("asia_pacific") == "etf_asia_pacific"
    assert cache_key_for_region("us") == "etf_us"
    assert cache_keys_for_region("us") == ("etf_us", ETF_SCREENER_CACHE_KEY)
    assert cache_keys_for_region("europe") == ("etf_europe",)
    assert universe_name_for("europe") == "Liquid Europe-listed UCITS ETFs"


def test_all_region_tickers_are_unique_within_each_universe():
    for region, tickers in ETF_UNIVERSES.items():
        assert len(tickers) == len(set(tickers)), region
        assert tickers
    assert "QQQ" in ALL_ETF_TICKERS
    assert "VWCE.DE" in ALL_ETF_TICKERS
    assert "BGBL.AX" in ALL_ETF_TICKERS


def test_frontend_static_symbols_include_every_region_ticker():
    text = Path("frontend/lib/etfRegions.ts").read_text(encoding="utf-8")
    for ticker in ALL_ETF_TICKERS:
        assert re.search(rf'"{re.escape(ticker)}"', text), ticker
