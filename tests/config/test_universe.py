from __future__ import annotations

from config.universe import (
    DEFAULT_STOCK_UNIVERSE,
    EMERGING_STOCK_UNIVERSE,
    EMERGING_UNIVERSE_FILTERS,
    SCAN_UNIVERSE_FILTERS,
    UNIVERSE_REGISTRY,
    universe_filters_for_ticker,
)


def test_spcx_is_in_emerging_and_global_universes():
    assert "SPCX" in EMERGING_STOCK_UNIVERSE
    assert "SPCX" in DEFAULT_STOCK_UNIVERSE
    assert "SPCX" in UNIVERSE_REGISTRY["global"]["tickers"]
    assert "SPCX" in UNIVERSE_REGISTRY["emerging"]["tickers"]


def test_emerging_tickers_use_new_listing_filters():
    assert universe_filters_for_ticker("spcx") == EMERGING_UNIVERSE_FILTERS
    assert universe_filters_for_ticker("AAPL") == SCAN_UNIVERSE_FILTERS

