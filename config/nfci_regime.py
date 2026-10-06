from __future__ import annotations

from typing import Any


# Pre-registered 2026-09-16. Do not retune these numbers against in-sample Sharpe,
# IC, or gated lift. NFCI-only v1: ANFCI and NFCI subindexes are not in the gate.
NFCI_RECIPE_VERSION = "nfci-gate-v1"
NFCI_RECIPE_FROZEN_ON = "2026-09-16"
NFCI_MODE = "shadow"

NFCI_SERIES_ID = "NFCI"
NFCI_SERIES_LABEL = "Chicago Fed National Financial Conditions Index"
ANFCI_SERIES_ID = "ANFCI"
ANFCI_INGEST_V1 = False

DELTA_WEEKS = 4
PERSISTENCE_WEEKS = 3
THROTTLE_WEIGHT = 0.50
SPY_VOL_WINDOW_SESSIONS = 20

# Chicago Fed NFCI is weekly ending Friday. Verified 2026-09-16:
# observation 2026-09-04 = -0.564, FRED updated 2026-09-10. Align joins to the
# release timestamp, not the week-end label. When ALFRED realtime_start is
# missing, lag the Friday label by this frozen calendar offset.
RELEASE_LAG_CALENDAR_DAYS = 6
ALFRED_REALTIME_START = "1776-07-04"
ALFRED_REALTIME_END = "9999-12-31"

MIN_NFCI_WEEKS_HARD = 104
MIN_NFCI_WEEKS_RECOMMENDED = 260
ALFRED_PRE_TRUNCATION_VINTAGE = "2026-03-31"

# Nested-model redundancy band vs KEEP HY OAS. Incremental IC/R² inside this
# band is treated as zero and trips the KILL switch.
REDUNDANCY_IC_EPSILON = 0.01
REDUNDANCY_R2_EPSILON = 0.01

# Discovered from origin/cursor/shadow-credit-hy-oas-regime-6c9c (credit-gate-v1,
# frozen 2026-09-15). Do not invent a second HY OAS recipe on this branch.
HY_KEEP_RECIPE_VERSION = "credit-gate-v1"
HY_KEEP_FROZEN_ON = "2026-09-15"
HY_KEEP_SOURCE_BRANCH = "cursor/shadow-credit-hy-oas-regime-6c9c"
HY_OAS_SERIES_ID = "BAMLH0A0HYM2"
IG_OAS_SERIES_ID = "BAMLC0A0CM"
HY_OAS_SERIES_LABEL = "ICE BofA US High Yield Index Option-Adjusted Spread"
IG_OAS_SERIES_LABEL = "ICE BofA US Corporate Index Option-Adjusted Spread"
HY_VELOCITY_WINDOW_SESSIONS = 20
HY_WEEKLY_WINDOW_SESSIONS = 5
HY_VELOCITY_WIDENING_BP = 30.0
HY_PERCENTILE_WINDOW_SESSIONS = 252
HY_PERCENTILE_MIN_OBSERVATIONS = 126
HY_PERCENTILE_THROTTLE = 80.0
HY_MIN_SERIES_SESSIONS_HARD = 252
HY_MIN_SERIES_SESSIONS_RECOMMENDED = 504

ICE_REDISTRIBUTION_NOTICE = (
    "ICE BofA OAS values retrieved via FRED or ALFRED are licensed by ICE Data "
    "Indices, LLC. St. Louis Fed redistribution of a limited public window does "
    "not grant OmniTrade the right to productize, republish, or display ICE-branded "
    "series. HY OAS is ingested here only as the discovered KEEP comparator for "
    "the NFCI nested kill switch. Do not surface ICE-branded prints in the product "
    "UI, APIs, or marketing without a separate ICE redistribution license."
)


def nfci_recipe_manifest() -> dict[str, Any]:
    return {
        "version": NFCI_RECIPE_VERSION,
        "frozen_on": NFCI_RECIPE_FROZEN_ON,
        "frozen": True,
        "mode": NFCI_MODE,
        "applied_impact": 0,
        "live_recommendation_changes": False,
        "is_stock_picker": False,
        "anfci_ingest_v1": ANFCI_INGEST_V1,
        "series": {
            "nfci": NFCI_SERIES_ID,
            "nfci_label": NFCI_SERIES_LABEL,
            "anfci": ANFCI_SERIES_ID,
            "anfci_in_v1": False,
        },
        "features": [
            "nfci_level",
            "nfci_d4w",
            "nfci_rising_streak",
        ],
        "gate": {
            "name": "nfci_persistently_rising_n_weeks",
            "throttle_when": (
                f"latest release-dated NFCI 4-week change is strictly positive "
                f"for {PERSISTENCE_WEEKS} consecutive weekly prints"
            ),
            "delta_weeks": DELTA_WEEKS,
            "persistence_weeks": PERSISTENCE_WEEKS,
            "throttle_weight": THROTTLE_WEIGHT,
            "level_in_gate": False,
            "anfci_in_gate": False,
            "unknown_when": (
                "NFCI level, 4-week change, or persistence streak cannot be computed "
                "on the release-dated panel"
            ),
        },
        "alignment": {
            "join_on": "release_date",
            "not": "observation_week_end",
            "alfred_realtime_start": ALFRED_REALTIME_START,
            "alfred_realtime_end": ALFRED_REALTIME_END,
            "fallback_release_lag_calendar_days": RELEASE_LAG_CALENDAR_DAYS,
            "verified_example": {
                "observation_week_end": "2026-09-04",
                "nfci": -0.564,
                "fred_updated": "2026-09-10",
                "fallback_release_date": "2026-09-10",
            },
        },
        "history_plan": {
            "min_weeks_hard": MIN_NFCI_WEEKS_HARD,
            "min_weeks_recommended": MIN_NFCI_WEEKS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
        },
        "keep_hy_oas_comparator": hy_keep_recipe_manifest(),
        "kill_switch": {
            "name": "redundant_with_hy_oas",
            "rule": (
                "KILL if nested NFCI features add |ΔIC| and |ΔR²| inside the "
                "redundancy band versus HY OAS alone AND HY+NFCI gated books show "
                "no primary-metric lift versus HY OAS alone in walk-forward."
            ),
            "redundancy_ic_epsilon": REDUNDANCY_IC_EPSILON,
            "redundancy_r2_epsilon": REDUNDANCY_R2_EPSILON,
        },
        "do_not_tune": True,
    }


def hy_keep_recipe_manifest() -> dict[str, Any]:
    return {
        "version": HY_KEEP_RECIPE_VERSION,
        "frozen_on": HY_KEEP_FROZEN_ON,
        "discovered_from_branch": HY_KEEP_SOURCE_BRANCH,
        "invented_on_this_branch": False,
        "frozen": True,
        "mode": "shadow",
        "applied_impact": 0,
        "series": {
            "hy_oas": HY_OAS_SERIES_ID,
            "ig_oas": IG_OAS_SERIES_ID,
            "hy_oas_label": HY_OAS_SERIES_LABEL,
            "ig_oas_label": IG_OAS_SERIES_LABEL,
        },
        "gate": {
            "name": "hy_oas_20d_widening_or_trailing_252_p80",
            "throttle_when": (
                f"20-session HY OAS change > {HY_VELOCITY_WIDENING_BP:.0f} bp "
                f"OR causal trailing-{HY_PERCENTILE_WINDOW_SESSIONS} HY OAS percentile "
                f">= {HY_PERCENTILE_THROTTLE:.0f}"
            ),
            "velocity_window_sessions": HY_VELOCITY_WINDOW_SESSIONS,
            "velocity_widening_bp": HY_VELOCITY_WIDENING_BP,
            "percentile_window_sessions": HY_PERCENTILE_WINDOW_SESSIONS,
            "percentile_min_observations": HY_PERCENTILE_MIN_OBSERVATIONS,
            "percentile_throttle": HY_PERCENTILE_THROTTLE,
            "throttle_weight": THROTTLE_WEIGHT,
            "weekly_delta_in_gate": False,
            "hy_ig_gap_in_gate": False,
        },
        "history_plan": {
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
            "min_sessions_hard": HY_MIN_SERIES_SESSIONS_HARD,
            "min_sessions_recommended": HY_MIN_SERIES_SESSIONS_RECOMMENDED,
        },
        "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
        "do_not_tune": True,
    }


__all__ = [
    "ALFRED_PRE_TRUNCATION_VINTAGE",
    "ALFRED_REALTIME_END",
    "ALFRED_REALTIME_START",
    "ANFCI_INGEST_V1",
    "ANFCI_SERIES_ID",
    "DELTA_WEEKS",
    "HY_KEEP_FROZEN_ON",
    "HY_KEEP_RECIPE_VERSION",
    "HY_KEEP_SOURCE_BRANCH",
    "HY_MIN_SERIES_SESSIONS_HARD",
    "HY_MIN_SERIES_SESSIONS_RECOMMENDED",
    "HY_OAS_SERIES_ID",
    "HY_OAS_SERIES_LABEL",
    "HY_PERCENTILE_MIN_OBSERVATIONS",
    "HY_PERCENTILE_THROTTLE",
    "HY_PERCENTILE_WINDOW_SESSIONS",
    "HY_VELOCITY_WIDENING_BP",
    "HY_VELOCITY_WINDOW_SESSIONS",
    "HY_WEEKLY_WINDOW_SESSIONS",
    "ICE_REDISTRIBUTION_NOTICE",
    "IG_OAS_SERIES_ID",
    "IG_OAS_SERIES_LABEL",
    "MIN_NFCI_WEEKS_HARD",
    "MIN_NFCI_WEEKS_RECOMMENDED",
    "NFCI_MODE",
    "NFCI_RECIPE_FROZEN_ON",
    "NFCI_RECIPE_VERSION",
    "NFCI_SERIES_ID",
    "NFCI_SERIES_LABEL",
    "PERSISTENCE_WEEKS",
    "REDUNDANCY_IC_EPSILON",
    "REDUNDANCY_R2_EPSILON",
    "RELEASE_LAG_CALENDAR_DAYS",
    "SPY_VOL_WINDOW_SESSIONS",
    "THROTTLE_WEIGHT",
    "hy_keep_recipe_manifest",
    "nfci_recipe_manifest",
]
