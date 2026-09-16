"""Pre-registered FINRA short-interest experiment constants.

Frozen before evaluation. Do not shop Δ or days-to-cover thresholds.
"""

from __future__ import annotations

from config.settings import DATA_DIR


EXPERIMENT_ID = "finra_short_interest_shadow_v1"
FEATURE_FAMILY = "short_interest"
FEATURE_FAMILY_LABEL = "FINRA biweekly short interest"
MODE = "shadow"
PROVENANCE = "FINRA_RULE_4560"
DATASET_GROUP = "otcMarket"
DATASET_NAME = "consolidatedShortInterest"
FALLBACK_DATASET_NAME = "equityShortInterestStandardized"
API_BASE_URL = "https://api.finra.org/data/group"
METADATA_BASE_URL = "https://api.finra.org/metadata/group"
CATALOG_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest"
FILES_URL = "https://www.finra.org/finra-data/browse-catalog/equity-short-interest/files"

# Rule 4560: FINRA publishes on the 7th business day after settlement.
# v1 uses weekday-only counting (Mon–Fri). Official calendars skip exchange
# holidays, so a holiday can push the true publication date by 1–2 sessions.
PUBLICATION_LAG_BUSINESS_DAYS = 7
EVENT_DATE_FIELD = "publication_date"

# Frozen screen/gate thresholds. Not squeeze products. Not post-hoc shopped.
PCT_CHANGE_HIGH = 20.0
PCT_CHANGE_LOW = -20.0
DAYS_TO_COVER_ELEVATED = 5.0
DAYS_TO_COVER_HIGH = 10.0

# % float is not a FINRA field. No frozen public-float series exists in
# OmniTrade, so v1 defers the feature rather than inventing a denominator.
PCT_FLOAT_STATUS = "deferred"
PCT_FLOAT_COVERAGE_FLOOR = 0.70
PCT_FLOAT_REASON = (
    "pctFloat is not a native FINRA field and OmniTrade has no frozen "
    "public-float series. v1 drops %float instead of computing an ad-hoc "
    "denominator from vendor floatShares."
)

WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 15
MIN_PUBLICATION_DATES = 36
MIN_FOLD_OOS_DATES = 6
MIN_CROSS_SECTION = 8
MIN_RESIDUALIZE_ROWS = 30
MIN_SHORT_VOLUME_COVERAGE = 0.70
SIGNIFICANCE_LEVEL = 0.05
PRIMARY_TARGET = "excess_20d"
SECONDARY_TARGETS = ("excess_60d", "abs_return_20d", "abs_return_60d")
SI_FEATURES = ("log_short_shares", "pct_change_prior", "days_to_cover")
FROZEN_GATE_FEATURES = (
    "delta_high",
    "delta_low",
    "dtc_elevated",
    "dtc_high",
)
CONTROLS = ("log_share_volume", "log_dollar_volume", "amihud_20")
BASELINE_FEATURE = "short_ratio"
SHORT_VOLUME_ASOF_CALENDAR_DAYS = 10
CACHE_DIR = DATA_DIR / "finra_short_interest"
CACHE_TTL_SECONDS = 6 * 60 * 60
TIMEOUT_SECONDS = 20
API_LIMIT = 5000

LEGAL_GATE = {
    "source": "FINRA Equity Short Interest (Rule 4560 biweekly settlement reports)",
    "catalog_url": CATALOG_URL,
    "files_url": FILES_URL,
    "dataset": DATASET_NAME,
    "use_class": "non_commercial_research",
    "commercial_use_allowed": False,
    "shipping_allowed": False,
    "requires_human_approval": True,
    "approval_owner": "Alvaro",
    "notes": (
        "FINRA publishes twice-monthly short-interest positions collected under "
        "Rule 4560. Event dates are publication dates, not settlement dates. "
        "This experiment is shadow-only and is not a squeeze narrative product."
    ),
}

NO_SQUEEZE_POLICY = (
    "No squeeze narrative products. Frozen Δ/DTC flags are positioning/liquidity "
    "screens only; they are never labeled as squeeze risk."
)
