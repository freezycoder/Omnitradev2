from __future__ import annotations

from config.industry_groups import (
    INDUSTRY_GROUP_MAP,
    INDUSTRY_GROUP_MAP_VERSION,
    INDUSTRY_GROUP_TAXONOMY,
    MIN_LIQUID_UNIVERSE_COVERAGE,
    map_manifest,
    universe_coverage,
)
from config.universe import DEFAULT_STOCK_UNIVERSE


def test_frozen_map_covers_the_liquid_universe():
    coverage = universe_coverage(DEFAULT_STOCK_UNIVERSE)

    assert coverage["map_version"] == INDUSTRY_GROUP_MAP_VERSION
    assert coverage["taxonomy"] == INDUSTRY_GROUP_TAXONOMY
    assert coverage["unmapped_tickers"] == []
    assert coverage["coverage"] >= MIN_LIQUID_UNIVERSE_COVERAGE
    assert coverage["meets_minimum_coverage"] is True
    assert set(INDUSTRY_GROUP_MAP) == set(DEFAULT_STOCK_UNIVERSE)


def test_map_is_explicitly_a_gics_proxy_not_ibd_197():
    manifest = map_manifest()

    assert manifest["is_ibd_197"] is False
    assert "proxy" in manifest["taxonomy"]
    assert manifest["proxy_label"] == "gics_subindustry_proxy_not_ibd_197"
    assert manifest["group_count"] >= 10
