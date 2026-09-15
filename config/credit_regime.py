from __future__ import annotations

from typing import Any


# Pre-registered 2026-09-15. Do not retune these numbers against in-sample Sharpe or drawdown.
CREDIT_RECIPE_VERSION = "credit-gate-v1"
CREDIT_RECIPE_FROZEN_ON = "2026-09-15"
CREDIT_MODE = "shadow"

HY_OAS_SERIES_ID = "BAMLH0A0HYM2"
IG_OAS_SERIES_ID = "BAMLC0A0CM"
HY_OAS_SERIES_LABEL = "ICE BofA US High Yield Index Option-Adjusted Spread"
IG_OAS_SERIES_LABEL = "ICE BofA US Corporate Index Option-Adjusted Spread"

VELOCITY_WINDOW_SESSIONS = 20
WEEKLY_WINDOW_SESSIONS = 5
VELOCITY_WIDENING_BP = 30.0
PERCENTILE_WINDOW_SESSIONS = 252
PERCENTILE_MIN_OBSERVATIONS = 126
PERCENTILE_THROTTLE = 80.0
THROTTLE_WEIGHT = 0.50
SPY_VOL_WINDOW_SESSIONS = 20

MIN_SERIES_SESSIONS_HARD = 252
MIN_SERIES_SESSIONS_RECOMMENDED = 504
ALFRED_PRE_TRUNCATION_VINTAGE = "2026-03-31"
LEAD_LAG_OFFSETS: tuple[int, ...] = (-20, -10, -5, 0, 5, 10, 20)

# Nested-model redundancy band. Incremental IC/R² inside this band is treated as zero.
REDUNDANCY_IC_EPSILON = 0.01
REDUNDANCY_R2_EPSILON = 0.01

ICE_REDISTRIBUTION_NOTICE = (
    "ICE BofA OAS values retrieved via FRED or ALFRED are licensed by ICE Data "
    "Indices, LLC. St. Louis Fed redistribution of a limited public window does "
    "not grant OmniTrade the right to productize, republish, or display ICE-branded "
    "series. This packet is internal shadow research ingest only. Do not surface "
    "ICE-branded prints in the product UI, APIs, or marketing without a separate "
    "ICE redistribution license."
)


def credit_recipe_manifest() -> dict[str, Any]:
    return {
        "version": CREDIT_RECIPE_VERSION,
        "frozen_on": CREDIT_RECIPE_FROZEN_ON,
        "frozen": True,
        "mode": CREDIT_MODE,
        "applied_impact": 0,
        "live_recommendation_changes": False,
        "is_stock_picker": False,
        "series": {
            "hy_oas": HY_OAS_SERIES_ID,
            "ig_oas": IG_OAS_SERIES_ID,
            "hy_oas_label": HY_OAS_SERIES_LABEL,
            "ig_oas_label": IG_OAS_SERIES_LABEL,
        },
        "features": [
            "hy_oas_level",
            "hy_oas_d20_bp",
            "hy_oas_d5_bp",
            "hy_ig_gap",
        ],
        "gate": {
            "name": "hy_oas_20d_widening_or_trailing_252_p80",
            "throttle_when": (
                f"20-session HY OAS change > {VELOCITY_WIDENING_BP:.0f} bp "
                f"OR causal trailing-{PERCENTILE_WINDOW_SESSIONS} HY OAS percentile "
                f">= {PERCENTILE_THROTTLE:.0f}"
            ),
            "velocity_window_sessions": VELOCITY_WINDOW_SESSIONS,
            "velocity_widening_bp": VELOCITY_WIDENING_BP,
            "percentile_window_sessions": PERCENTILE_WINDOW_SESSIONS,
            "percentile_min_observations": PERCENTILE_MIN_OBSERVATIONS,
            "percentile_throttle": PERCENTILE_THROTTLE,
            "throttle_weight": THROTTLE_WEIGHT,
            "weekly_delta_in_gate": False,
            "hy_ig_gap_in_gate": False,
            "unknown_when": (
                "HY OAS is missing or the 20-session change cannot be computed"
            ),
        },
        "history_plan": {
            "fred_public_window_note": (
                "Starting April 2026 the public FRED series retains about three years "
                "of observations. That window is sufficient for this frozen recipe "
                "(20-session velocity, trailing-252 percentile, 3 walk-forward folds). "
                "If the window shrinks below 252 sessions, pull ALFRED vintage "
                f"{ALFRED_PRE_TRUNCATION_VINTAGE} or licensed ICE; otherwise FAIL data-blocked."
            ),
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
            "min_sessions_hard": MIN_SERIES_SESSIONS_HARD,
            "min_sessions_recommended": MIN_SERIES_SESSIONS_RECOMMENDED,
            "march_2020_is_tune_target": False,
        },
        "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
        "do_not_tune": True,
    }
