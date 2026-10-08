from __future__ import annotations

from typing import Any

from config.universe import DEFAULT_STOCK_UNIVERSE


# Pre-registered 2026-09-14. Do not retune these numbers against in-sample IC or hit-rate.
BREADTH_RECIPE_VERSION = "breadth-gate-v1"
BREADTH_RECIPE_FROZEN_ON = "2026-09-14"
BREADTH_MODE = "shadow"

SPY_SYMBOL = "SPY"
RSP_SYMBOL = "RSP"
EQUAL_WEIGHT_PROXY_LABEL = "equal_weight_universe"

MA_WINDOWS: tuple[int, ...] = (20, 50, 200)
GATE_MA_WINDOW = 50
GATE_PCT_ABOVE_50DMA_MIN = 55.0
GATE_AD_DIVERGENCE_SESSIONS = 10
NEW_HIGH_LOW_LOOKBACK_SESSIONS = 252

MIN_PCT_ABOVE_MA_COVERAGE = 0.80
MIN_HISTORY_FOR_200DMA = 200
MIN_HISTORY_SESSIONS_RECOMMENDED = 504

# Nested-model redundancy band. Incremental IC/R² inside this band is treated as zero.
REDUNDANCY_IC_EPSILON = 0.01
REDUNDANCY_R2_EPSILON = 0.01

DEFAULT_BREADTH_UNIVERSE: tuple[str, ...] = tuple(DEFAULT_STOCK_UNIVERSE)


def breadth_recipe_manifest() -> dict[str, Any]:
    return {
        "version": BREADTH_RECIPE_VERSION,
        "frozen_on": BREADTH_RECIPE_FROZEN_ON,
        "frozen": True,
        "mode": BREADTH_MODE,
        "metric_set": [
            "advances",
            "declines",
            "advance_decline_line",
            "up_volume",
            "down_volume",
            "pct_above_20dma",
            "pct_above_50dma",
            "pct_above_200dma",
            "spy_return_vs_equal_weight",
            "spy_return_vs_rsp_if_available",
        ],
        "optional_secondary_metrics": ["new_highs_252", "new_lows_252"],
        "excluded_series": ["TICK", "intraday_tick", "TRIN"],
        "gate": {
            "name": "pct_above_50dma_and_ad_not_diverging_vs_spy",
            "pct_above_50dma_min": GATE_PCT_ABOVE_50DMA_MIN,
            "ad_divergence_sessions": GATE_AD_DIVERGENCE_SESSIONS,
            "divergence_rule": (
                "closed when SPY N-session return is strictly positive "
                "and the advance/decline line declined over the same N sessions"
            ),
            "unknown_when": (
                "pct_above_50dma coverage is below 80%, or 10-session SPY/A-D inputs are missing"
            ),
        },
        "cap_weight_proxy": {
            "primary": SPY_SYMBOL,
            "equal_weight_preferred": RSP_SYMBOL,
            "fallback": EQUAL_WEIGHT_PROXY_LABEL,
        },
        "do_not_tune": True,
    }
