from __future__ import annotations

from datetime import date

from config.market_breadth import (
    BREADTH_RECIPE_FROZEN_ON,
    BREADTH_RECIPE_VERSION,
    GATE_AD_DIVERGENCE_SESSIONS,
    GATE_PCT_ABOVE_50DMA_MIN,
    MA_WINDOWS,
    MIN_PCT_ABOVE_MA_COVERAGE,
    REDUNDANCY_IC_EPSILON,
    REDUNDANCY_R2_EPSILON,
    breadth_recipe_manifest,
)


def test_frozen_gate_recipe_is_not_available_for_tuning():
    manifest = breadth_recipe_manifest()

    assert BREADTH_RECIPE_VERSION == "breadth-gate-v1"
    assert BREADTH_RECIPE_FROZEN_ON == "2026-09-14"
    assert GATE_PCT_ABOVE_50DMA_MIN == 55.0
    assert GATE_AD_DIVERGENCE_SESSIONS == 10
    assert MA_WINDOWS == (20, 50, 200)
    assert MIN_PCT_ABOVE_MA_COVERAGE == 0.80
    assert REDUNDANCY_IC_EPSILON == 0.01
    assert REDUNDANCY_R2_EPSILON == 0.01
    assert manifest["frozen"] is True
    assert manifest["do_not_tune"] is True
    assert manifest["gate"]["pct_above_50dma_min"] == 55.0
    assert "TICK" in manifest["excluded_series"]
    assert date.fromisoformat(BREADTH_RECIPE_FROZEN_ON) <= date(2026, 9, 14)
