from __future__ import annotations

from typing import Any


# Pre-registered 2026-09-17. Do not retune these numbers against in-sample Sharpe,
# IC, or gated lift. Headline KCRORO is the only v1 gate input; subindexes are
# ingested for the frozen equity-leg ablation, not stacked until significant.
KCRORO_RECIPE_VERSION = "kcroro-gate-v1"
KCRORO_RECIPE_FROZEN_ON = "2026-09-17"
KCRORO_MODE = "shadow"

KCRORO_SERIES_ID = "KCRORO"
KCRORO_SERIES_LABEL = "KC Fed Risk-On Risk-Off Index"
KCRORO_SPREADS_SERIES_ID = "KCROROS"
KCRORO_EQUITY_SERIES_ID = "KCROROE"
KCRORO_LIQUIDITY_SERIES_ID = "KCROROL"
KCRORO_FXGOLD_SERIES_ID = "KCROROG"
KCRORO_SPREADS_LABEL = "KC Fed RORO spreads subindex"
KCRORO_EQUITY_LABEL = "KC Fed RORO equities subindex"
KCRORO_LIQUIDITY_LABEL = "KC Fed RORO liquidity/funding subindex"
KCRORO_FXGOLD_LABEL = "KC Fed RORO FX-gold subindex"

# Positive ≈ risk-off, negative ≈ risk-on. Frozen once: throttle when the latest
# released print is strictly positive OR the causal 20-session sum of daily PCA
# shocks is strictly positive. Both thresholds are natural zeros — not shopped.
LEVEL_THROTTLE = 0.0
SHOCK_SUM_WINDOW_SESSIONS = 20
SHOCK_SUM_THROTTLE = 0.0
THROTTLE_WEIGHT = 0.50
SPY_VOL_WINDOW_SESSIONS = 20

# Daily FRED print is typically available the next morning. Search-verified
# 2026-09-08 = 0.1814, updated 2026-09-09. Join on release_date, never the
# observation date. When ALFRED realtime_start is missing, lag by this offset.
RELEASE_LAG_CALENDAR_DAYS = 1
ALFRED_REALTIME_START = "1776-07-04"
ALFRED_REALTIME_END = "9999-12-31"

MIN_KCRORO_SESSIONS_HARD = 252
MIN_KCRORO_SESSIONS_RECOMMENDED = 504
ALFRED_PRE_TRUNCATION_VINTAGE = "2026-03-31"

# Nested-model redundancy band vs KEEP HY OAS + NFCI. Incremental IC/R² inside
# this band is treated as zero and trips the KILL switch.
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

# Discovered from origin/cursor/shadow-nfci-regime-gate-0e2b (nfci-gate-v1,
# frozen 2026-09-16). Do not invent a second NFCI recipe on this branch.
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

ICE_REDISTRIBUTION_NOTICE = (
    "ICE BofA OAS values retrieved via FRED or ALFRED are licensed by ICE Data "
    "Indices, LLC. St. Louis Fed redistribution of a limited public window does "
    "not grant OmniTrade the right to productize, republish, or display ICE-branded "
    "series. HY OAS is ingested here only as the discovered KEEP comparator for "
    "the KCRORO nested kill switch. Do not surface ICE-branded prints in the product "
    "UI, APIs, or marketing without a separate ICE redistribution license."
)

KCRORO_CITATION = (
    "Chari, Anusha, Karlye Dilts Stedman, and Christian Lundblad, 2024, "
    "\"Risk-On Risk-Off: A Multifaceted Approach to Measuring Global Investor "
    "Risk Appetite,\" Federal Reserve Bank of Kansas City Research Working "
    "Paper no. 24-12."
)
KCRORO_SOURCE_URL = "https://www.kansascityfed.org/data-and-trends/risk-on-risk-off-index/"
KCRORO_README_URL = "https://www.kansascityfed.org/documents/10930/RORO_Index_README.pdf"
KCRORO_FRED_URL = "https://fred.stlouisfed.org/series/KCRORO"
KCRORO_PAPER_URL = (
    "https://www.kansascityfed.org/research/research-working-papers/"
    "risk-on-risk-off-a-multifaceted-approach-to-measuring-global-investor-risk-appetite/"
)


def kcroro_recipe_manifest() -> dict[str, Any]:
    return {
        "version": KCRORO_RECIPE_VERSION,
        "frozen_on": KCRORO_RECIPE_FROZEN_ON,
        "frozen": True,
        "mode": KCRORO_MODE,
        "applied_impact": 0,
        "live_recommendation_changes": False,
        "is_stock_picker": False,
        "series": {
            "kcroro": KCRORO_SERIES_ID,
            "kcroro_label": KCRORO_SERIES_LABEL,
            "spreads": KCRORO_SPREADS_SERIES_ID,
            "equities": KCRORO_EQUITY_SERIES_ID,
            "liquidity": KCRORO_LIQUIDITY_SERIES_ID,
            "fx_gold": KCRORO_FXGOLD_SERIES_ID,
        },
        "features": [
            "kcroro_level",
            "kcroro_shock_sum_20d",
            "kcroro_spreads",
            "kcroro_liquidity",
            "kcroro_fxgold",
        ],
        "gate": {
            "name": "kcroro_positive_or_20d_shock_sum_positive",
            "throttle_when": (
                f"latest release-dated KCRORO > {LEVEL_THROTTLE:g} "
                f"OR causal {SHOCK_SUM_WINDOW_SESSIONS}-session sum of KCRORO shocks "
                f"> {SHOCK_SUM_THROTTLE:g}"
            ),
            "level_throttle": LEVEL_THROTTLE,
            "shock_sum_window_sessions": SHOCK_SUM_WINDOW_SESSIONS,
            "shock_sum_throttle": SHOCK_SUM_THROTTLE,
            "throttle_weight": THROTTLE_WEIGHT,
            "subindexes_in_gate": False,
            "equity_subindex_in_gate": False,
            "unknown_when": (
                "KCRORO level is missing or the 20-session shock sum cannot be "
                "computed on the release-dated panel"
            ),
        },
        "ablation": {
            "name": "drop_equity_subindex",
            "rule": (
                "Apply the same frozen level/sum rule to the equal-weight mean of "
                "spreads (KCROROS), liquidity (KCROROL), and FX-gold (KCROROG). "
                "If headline lift vanishes after dropping equities (KCROROE), "
                "KILL the equity leg as circular with SPX."
            ),
            "requires_all_non_equity_legs": True,
        },
        "alignment": {
            "join_on": "release_date",
            "not": "observation_date",
            "alfred_realtime_start": ALFRED_REALTIME_START,
            "alfred_realtime_end": ALFRED_REALTIME_END,
            "fallback_release_lag_calendar_days": RELEASE_LAG_CALENDAR_DAYS,
            "verified_example": {
                "observation_date": "2026-09-08",
                "kcroro": 0.1814,
                "fred_updated": "2026-09-09",
                "fallback_release_date": "2026-09-09",
            },
        },
        "history_plan": {
            "min_sessions_hard": MIN_KCRORO_SESSIONS_HARD,
            "min_sessions_recommended": MIN_KCRORO_SESSIONS_RECOMMENDED,
            "alfred_vintage": ALFRED_PRE_TRUNCATION_VINTAGE,
        },
        "citation": {
            "text": KCRORO_CITATION,
            "source_url": KCRORO_SOURCE_URL,
            "readme_url": KCRORO_README_URL,
            "fred_url": KCRORO_FRED_URL,
            "paper_url": KCRORO_PAPER_URL,
        },
        "keep_hy_oas_comparator": hy_keep_recipe_manifest(),
        "keep_nfci_comparator": nfci_keep_recipe_manifest(),
        "kill_switch": {
            "name": "redundant_with_hy_oas_and_nfci_or_equity_leg_only",
            "rule": (
                "KILL if nested KCRORO features add |ΔIC| and |ΔR²| inside the "
                "redundancy band versus HY OAS + NFCI AND HY+NFCI+RORO gated books "
                "show no primary-metric lift versus HY+NFCI in walk-forward; OR if "
                "headline lift vanishes after dropping the equity subindex."
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
            "anfci_in_v1": False,
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
    "KCRORO_CITATION",
    "KCRORO_EQUITY_LABEL",
    "KCRORO_EQUITY_SERIES_ID",
    "KCRORO_FRED_URL",
    "KCRORO_FXGOLD_LABEL",
    "KCRORO_FXGOLD_SERIES_ID",
    "KCRORO_LIQUIDITY_LABEL",
    "KCRORO_LIQUIDITY_SERIES_ID",
    "KCRORO_MODE",
    "KCRORO_PAPER_URL",
    "KCRORO_README_URL",
    "KCRORO_RECIPE_FROZEN_ON",
    "KCRORO_RECIPE_VERSION",
    "KCRORO_SERIES_ID",
    "KCRORO_SERIES_LABEL",
    "KCRORO_SOURCE_URL",
    "KCRORO_SPREADS_LABEL",
    "KCRORO_SPREADS_SERIES_ID",
    "LEVEL_THROTTLE",
    "MIN_KCRORO_SESSIONS_HARD",
    "MIN_KCRORO_SESSIONS_RECOMMENDED",
    "MIN_NFCI_WEEKS_HARD",
    "MIN_NFCI_WEEKS_RECOMMENDED",
    "NFCI_DELTA_WEEKS",
    "NFCI_KEEP_FROZEN_ON",
    "NFCI_KEEP_RECIPE_VERSION",
    "NFCI_KEEP_SOURCE_BRANCH",
    "NFCI_PERSISTENCE_WEEKS",
    "NFCI_RELEASE_LAG_CALENDAR_DAYS",
    "NFCI_SERIES_ID",
    "NFCI_SERIES_LABEL",
    "REDUNDANCY_IC_EPSILON",
    "REDUNDANCY_R2_EPSILON",
    "RELEASE_LAG_CALENDAR_DAYS",
    "SHOCK_SUM_THROTTLE",
    "SHOCK_SUM_WINDOW_SESSIONS",
    "SPY_VOL_WINDOW_SESSIONS",
    "THROTTLE_WEIGHT",
    "hy_keep_recipe_manifest",
    "kcroro_recipe_manifest",
    "nfci_keep_recipe_manifest",
]
