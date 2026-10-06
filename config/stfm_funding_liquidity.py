from __future__ import annotations

from typing import Any


# Pre-registered 2026-09-17. Do not retune these numbers against in-sample Sharpe,
# IC, gated lift, Sep 2019, or Mar 2020. Mnemonic list is frozen before eval.
STFM_RECIPE_VERSION = "stfm-gate-v1"
STFM_RECIPE_FROZEN_ON = "2026-09-17"
STFM_MODE = "shadow"

OFR_STFM_BASE_URL = "https://data.financialresearch.gov/v1"
OFR_STFM_USER_AGENT = "OmniTrade/1.0 research-shadow"

MNEMONIC_DVP_VOLUME = "REPO-DVP_TV_TOT-P"
MNEMONIC_GCF_VOLUME = "REPO-GCF_TV_TOT-P"
MNEMONIC_MMF_TOTAL = "MMF-MMF_TOT-M"
MNEMONIC_SOFR = "FNYR-SOFR-A"
MNEMONIC_EFFR = "FNYR-EFFR-A"

FROZEN_MNEMONICS: tuple[str, ...] = (
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    MNEMONIC_EFFR,
)

DAILY_VOLUME_MNEMONICS: tuple[str, ...] = (MNEMONIC_DVP_VOLUME, MNEMONIC_GCF_VOLUME)
DAILY_RATE_MNEMONICS: tuple[str, ...] = (MNEMONIC_SOFR, MNEMONIC_EFFR)

# Verified 2026-09-17: DVP/GCF/SOFR/EFFR obs 2026-09-15, STFM last_update 2026-09-16.
DAILY_RELEASE_LAG_CALENDAR_DAYS = 1
# Verified 2026-09-17: MMF-MMF_TOT-M obs 2026-07-31, last_update 2026-08-17.
MMF_RELEASE_LAG_CALENDAR_DAYS = 20

ZSCORE_WINDOW_SESSIONS = 252
ZSCORE_MIN_OBSERVATIONS = 126
VOLUME_DELTA_SHORT_SESSIONS = 5
VOLUME_DELTA_LONG_SESSIONS = 20
VOLUME_ZSCORE_DROP = -1.0
SOFR_EFFR_WIDEN_BP = 3.0
SOFR_EFFR_DELTA_SESSIONS = 5
MMF_ZSCORE_WINDOW_MONTHS = 36
MMF_ZSCORE_MIN_OBSERVATIONS = 18

THROTTLE_WEIGHT = 0.50
SPY_VOL_WINDOW_SESSIONS = 20

MIN_STFM_SESSIONS_HARD = 252
MIN_STFM_SESSIONS_RECOMMENDED = 504
MIN_MMF_MONTHS_HARD = 24

REDUNDANCY_IC_EPSILON = 0.01
REDUNDANCY_R2_EPSILON = 0.01

RORO_INGEST_V1 = False
RORO_DISCOVERY = (
    "RORO is not present on main or on remote shadow-regime branches. "
    "v1 does not invent a RORO proxy. Nested kill is HY OAS + NFCI."
)

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

# Discovered from origin/cursor/shadow-nfci-regime-gate-0e2b (nfci-gate-v1,
# frozen 2026-09-16). Funding-leg composite only; ANFCI/subindexes stay out.
NFCI_KEEP_RECIPE_VERSION = "nfci-gate-v1"
NFCI_KEEP_FROZEN_ON = "2026-09-16"
NFCI_KEEP_SOURCE_BRANCH = "cursor/shadow-nfci-regime-gate-0e2b"
NFCI_SERIES_ID = "NFCI"
NFCI_SERIES_LABEL = "Chicago Fed National Financial Conditions Index"
NFCI_DELTA_WEEKS = 4
NFCI_PERSISTENCE_WEEKS = 3
NFCI_RELEASE_LAG_CALENDAR_DAYS = 6
MIN_NFCI_WEEKS_HARD = 104
MIN_NFCI_WEEKS_RECOMMENDED = 260
ANFCI_INGEST_V1 = False

ALFRED_REALTIME_START = "1776-07-04"
ALFRED_REALTIME_END = "9999-12-31"
ALFRED_PRE_TRUNCATION_VINTAGE = "2026-03-31"

ICE_REDISTRIBUTION_NOTICE = (
    "ICE BofA OAS values retrieved via FRED or ALFRED are licensed by ICE Data "
    "Indices, LLC. St. Louis Fed redistribution of a limited public window does "
    "not grant OmniTrade the right to productize, republish, or display ICE-branded "
    "series. HY OAS is ingested here only as the discovered KEEP comparator for "
    "the STFM nested kill switch. Do not surface ICE-branded prints in the product "
    "UI, APIs, or marketing without a separate ICE redistribution license."
)


def stfm_recipe_manifest() -> dict[str, Any]:
    return {
        "version": STFM_RECIPE_VERSION,
        "frozen_on": STFM_RECIPE_FROZEN_ON,
        "frozen": True,
        "mode": STFM_MODE,
        "applied_impact": 0,
        "live_recommendation_changes": False,
        "is_stock_picker": False,
        "mnemonic_shopping": False,
        "series": {
            "dvp_volume": MNEMONIC_DVP_VOLUME,
            "gcf_volume": MNEMONIC_GCF_VOLUME,
            "mmf_total": MNEMONIC_MMF_TOTAL,
            "sofr": MNEMONIC_SOFR,
            "effr": MNEMONIC_EFFR,
            "frozen_mnemonics": list(FROZEN_MNEMONICS),
        },
        "features": [
            "dvp_volume",
            "gcf_volume",
            "dvp_z",
            "gcf_z",
            "dvp_d5_pct",
            "dvp_d20_pct",
            "gcf_d5_pct",
            "gcf_d20_pct",
            "mmf_total",
            "mmf_z",
            "mmf_d1m_pct",
            "sofr",
            "effr",
            "sofr_effr_spread_bp",
            "sofr_effr_d5_bp",
        ],
        "gate": {
            "name": "joint_volume_drop_and_spread_widen",
            "throttle_when": (
                f"causal DVP z-score <= {VOLUME_ZSCORE_DROP:.1f} or GCF z-score "
                f"<= {VOLUME_ZSCORE_DROP:.1f}, AND {SOFR_EFFR_DELTA_SESSIONS}-session "
                f"SOFR-EFFR change > {SOFR_EFFR_WIDEN_BP:.0f} bp"
            ),
            "volume_zscore_drop": VOLUME_ZSCORE_DROP,
            "sofr_effr_widen_bp": SOFR_EFFR_WIDEN_BP,
            "sofr_effr_delta_sessions": SOFR_EFFR_DELTA_SESSIONS,
            "mmf_in_gate": False,
            "throttle_weight": THROTTLE_WEIGHT,
            "unknown_when": (
                "Volume z-score cannot be computed for both DVP and GCF, or the "
                "5-session SOFR-EFFR change is missing. Null OFR prints are not zero-filled."
            ),
        },
        "sofr_only_control": {
            "name": "sofr_effr_spread_widen",
            "throttle_when": (
                f"{SOFR_EFFR_DELTA_SESSIONS}-session SOFR-EFFR change > "
                f"{SOFR_EFFR_WIDEN_BP:.0f} bp"
            ),
            "volumes_in_gate": False,
            "mmf_in_gate": False,
        },
        "alignment": {
            "join_on": "release_date",
            "not": "observation_date",
            "daily_release_lag_calendar_days": DAILY_RELEASE_LAG_CALENDAR_DAYS,
            "mmf_release_lag_calendar_days": MMF_RELEASE_LAG_CALENDAR_DAYS,
            "verified_example": {
                "daily_observation": "2026-09-15",
                "daily_last_update": "2026-09-16",
                "daily_release_date": "2026-09-16",
                "mmf_observation": "2026-07-31",
                "mmf_last_update": "2026-08-17",
                "mmf_release_date": "2026-08-20",
            },
        },
        "history_plan": {
            "min_sessions_hard": MIN_STFM_SESSIONS_HARD,
            "min_sessions_recommended": MIN_STFM_SESSIONS_RECOMMENDED,
            "min_mmf_months_hard": MIN_MMF_MONTHS_HARD,
        },
        "keep_hy_oas_comparator": hy_keep_recipe_manifest(),
        "keep_nfci_comparator": nfci_keep_recipe_manifest(),
        "roro": {
            "ingest_v1": RORO_INGEST_V1,
            "discovered": False,
            "invented_on_this_branch": False,
            "note": RORO_DISCOVERY,
        },
        "kill_switch": {
            "nested_vs_hy_nfci": (
                "KILL if STFM adds |ΔIC| and |ΔR²| inside the redundancy band versus "
                "HY+NFCI AND HY+NFCI+STFM shows no primary-metric gated lift versus "
                "HY+NFCI."
            ),
            "sofr_only": (
                "KILL if volumes+MMF add |ΔIC| and |ΔR²| inside the redundancy band "
                "versus SOFR-only AND the full pack shows no primary-metric gated lift "
                "versus SOFR-only."
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


def nfci_keep_recipe_manifest() -> dict[str, Any]:
    return {
        "version": NFCI_KEEP_RECIPE_VERSION,
        "frozen_on": NFCI_KEEP_FROZEN_ON,
        "discovered_from_branch": NFCI_KEEP_SOURCE_BRANCH,
        "invented_on_this_branch": False,
        "frozen": True,
        "mode": "shadow",
        "applied_impact": 0,
        "series": {
            "nfci": NFCI_SERIES_ID,
            "nfci_label": NFCI_SERIES_LABEL,
            "anfci_in_v1": ANFCI_INGEST_V1,
        },
        "gate": {
            "name": "nfci_persistently_rising_n_weeks",
            "throttle_when": (
                f"latest release-dated NFCI 4-week change is strictly positive "
                f"for {NFCI_PERSISTENCE_WEEKS} consecutive weekly prints"
            ),
            "delta_weeks": NFCI_DELTA_WEEKS,
            "persistence_weeks": NFCI_PERSISTENCE_WEEKS,
            "throttle_weight": THROTTLE_WEIGHT,
            "level_in_gate": False,
            "anfci_in_gate": False,
        },
        "alignment": {
            "join_on": "release_date",
            "fallback_release_lag_calendar_days": NFCI_RELEASE_LAG_CALENDAR_DAYS,
        },
        "history_plan": {
            "min_weeks_hard": MIN_NFCI_WEEKS_HARD,
            "min_weeks_recommended": MIN_NFCI_WEEKS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
        },
        "do_not_tune": True,
    }


__all__ = [
    "ALFRED_PRE_TRUNCATION_VINTAGE",
    "ALFRED_REALTIME_END",
    "ALFRED_REALTIME_START",
    "ANFCI_INGEST_V1",
    "DAILY_RATE_MNEMONICS",
    "DAILY_RELEASE_LAG_CALENDAR_DAYS",
    "DAILY_VOLUME_MNEMONICS",
    "FROZEN_MNEMONICS",
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
    "MIN_MMF_MONTHS_HARD",
    "MIN_NFCI_WEEKS_HARD",
    "MIN_NFCI_WEEKS_RECOMMENDED",
    "MIN_STFM_SESSIONS_HARD",
    "MIN_STFM_SESSIONS_RECOMMENDED",
    "MMF_RELEASE_LAG_CALENDAR_DAYS",
    "MMF_ZSCORE_MIN_OBSERVATIONS",
    "MMF_ZSCORE_WINDOW_MONTHS",
    "MNEMONIC_DVP_VOLUME",
    "MNEMONIC_EFFR",
    "MNEMONIC_GCF_VOLUME",
    "MNEMONIC_MMF_TOTAL",
    "MNEMONIC_SOFR",
    "NFCI_DELTA_WEEKS",
    "NFCI_KEEP_FROZEN_ON",
    "NFCI_KEEP_RECIPE_VERSION",
    "NFCI_KEEP_SOURCE_BRANCH",
    "NFCI_PERSISTENCE_WEEKS",
    "NFCI_RELEASE_LAG_CALENDAR_DAYS",
    "NFCI_SERIES_ID",
    "NFCI_SERIES_LABEL",
    "OFR_STFM_BASE_URL",
    "OFR_STFM_USER_AGENT",
    "REDUNDANCY_IC_EPSILON",
    "REDUNDANCY_R2_EPSILON",
    "RORO_DISCOVERY",
    "RORO_INGEST_V1",
    "SOFR_EFFR_DELTA_SESSIONS",
    "SOFR_EFFR_WIDEN_BP",
    "SPY_VOL_WINDOW_SESSIONS",
    "STFM_MODE",
    "STFM_RECIPE_FROZEN_ON",
    "STFM_RECIPE_VERSION",
    "THROTTLE_WEIGHT",
    "VOLUME_DELTA_LONG_SESSIONS",
    "VOLUME_DELTA_SHORT_SESSIONS",
    "VOLUME_ZSCORE_DROP",
    "ZSCORE_MIN_OBSERVATIONS",
    "ZSCORE_WINDOW_SESSIONS",
    "hy_keep_recipe_manifest",
    "nfci_keep_recipe_manifest",
    "stfm_recipe_manifest",
]
