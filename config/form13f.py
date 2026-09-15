from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from config.settings import DATA_DIR


# Frozen before any evaluation. Do not retune K, streak length, AUM floor,
# event dating, or the notable-manager taxonomy after seeing returns.

TAXONOMY_VERSION = "v1"
CLUSTER_MIN_NOTABLE_MANAGERS = 3
STREAK_MIN_QUARTERS = 2
NOTABLE_AUM_FLOOR_USD = 10_000_000_000.0

FORWARD_HORIZONS_DAYS = (20, 60, 120)
PRIMARY_HORIZON_DAYS = 20
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 45
MIN_FOLD_EVENTS = 8
REQUIRED_POSITIVE_FOLDS = 2

VALUE_UNITS_CUTOVER = "2023-01-03"
FORM13F_MODE = "shadow"
FORM13F_APPLIED_IMPACT = 0
FORM13F_MAX_MODELED_IMPACT = 6
PRIMARY_SOURCE = "sec_form13f_data_sets"

FORM13F_CACHE_DIR = DATA_DIR / "form13f_cache"
FORM13F_HOLDINGS_FILE = FORM13F_CACHE_DIR / "holdings.json"
FORM13F_LAST_RUN_FILE = FORM13F_CACHE_DIR / "last_experiment.json"

SEC_FORM13F_DATASET_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets"
)
SEC_FORM13F_README_URL = "https://www.sec.gov/files/form_13f_readme.pdf"
SEC_FORM13F_BASE_URL = "https://www.sec.gov"
SEC_FORM13F_STRUCTURED_PREFIX = "/files/structureddata/data/form-13f-data-sets"
SEC_FORM13F_DSI_PREFIX = "/files/datastandardsinnovation/data/form-13f-data-sets"

# Publication windows after 13F due dates (Feb/May/Aug/Nov). Event dating still
# uses each filing's SUBMISSION.FILING_DATE, never the reportable quarter-end.
POST_2023_PUBLICATION_ZIPS = (
    "01jan2024-29feb2024_form13f.zip",
    "01mar2024-31may2024_form13f.zip",
    "01jun2024-31aug2024_form13f.zip",
    "01sep2024-30nov2024_form13f.zip",
    "01dec2024-28feb2025_form13f.zip",
    "01mar2025-31may2025_form13f.zip",
    "01jun2025-31aug2025_form13f.zip",
    "01sep2025-30nov2025_form13f.zip",
    "01dec2025-28feb2026_form13f.zip",
    "01mar2026-31may2026_form13f.zip",
)
DSI_PUBLICATION_ZIPS = ("01jun2026-31aug2026_form13f.zip",)

ETF_CHURN_PASSIVE_ENTER_THRESHOLD = 2
MATCH_MAX_LOG_ADV_DISTANCE = 0.75

EXPERIMENT_PROTOCOL = MappingProxyType(
    {
        "hypothesis": (
            "Names with >=K notable 13F managers newly entering (or exiting) the "
            "same reportable quarter, and/or multi-quarter accumulation streaks, "
            "show calibratable forward excess returns after the public filing "
            "window — orthogonal to Form 4 daily insider flow."
        ),
        "mode": FORM13F_MODE,
        "applied_impact": FORM13F_APPLIED_IMPACT,
        "automatic_activation": False,
        "live_recommendation_changes": False,
        "primary_source": PRIMARY_SOURCE,
        "taxonomy_version": TAXONOMY_VERSION,
        "cluster_k": CLUSTER_MIN_NOTABLE_MANAGERS,
        "streak_min_quarters": STREAK_MIN_QUARTERS,
        "notable_aum_floor_usd": NOTABLE_AUM_FLOOR_USD,
        "event_date_rule": "kth_notable_manager_filing_date",
        "forbid_quarter_end_dating": True,
        "value_units_cutover": VALUE_UNITS_CUTOVER,
        "forward_horizons_days": FORWARD_HORIZONS_DAYS,
        "primary_horizon_days": PRIMARY_HORIZON_DAYS,
        "walk_forward_folds": WALK_FORWARD_FOLDS,
        "walk_forward_embargo_days": WALK_FORWARD_EMBARGO_DAYS,
        "min_fold_events": MIN_FOLD_EVENTS,
        "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
        "primary_portfolio": "cluster_entry_etf_filtered",
        "baselines": (
            "no_cluster_feature",
            "single_notable_holder_entry",
            "size_liquidity_matched_non_cluster",
        ),
        "success_rule": (
            f"Pre-registered K={CLUSTER_MIN_NOTABLE_MANAGERS} cluster-entry "
            f"(or streak) mean size/liquidity-matched {PRIMARY_HORIZON_DAYS}d "
            f"excess > 0 in >={REQUIRED_POSITIVE_FOLDS}/{WALK_FORWARD_FOLDS} "
            "walk-forward folds after lag-correct dating; coverage adequate."
        ),
        "fail_rule": (
            "No matched excess after lag-correct dating; OR taxonomy instability "
            "would be required to recover a result; OR ETF/index churn explains "
            "the book; OR any remaining edge is subsumed by size/liquidity match."
        ),
        "overfitting_mitigations": (
            "taxonomy_frozen_before_eval",
            "k_frozen_at_3",
            "event_date_is_filing_availability_not_quarter_end",
            "etf_churn_filter_pre_registered",
        ),
        "dataset_page": SEC_FORM13F_DATASET_PAGE_URL,
        "coverage_start": "2013-05 XML 13F data sets onward",
    }
)


def quarterly_zip_filename(year: int, quarter: int) -> str:
    if quarter not in {1, 2, 3, 4}:
        raise ValueError(f"Quarter must be 1-4, received {quarter}.")
    return f"{int(year)}q{int(quarter)}_form13f.zip"


def historical_quarter_zip_paths() -> tuple[str, ...]:
    paths: list[str] = []
    for year in range(2013, 2024):
        start_quarter = 2 if year == 2013 else 1
        for quarter in range(start_quarter, 5):
            paths.append(f"{SEC_FORM13F_STRUCTURED_PREFIX}/{quarterly_zip_filename(year, quarter)}")
    return tuple(paths)


def publication_zip_paths() -> tuple[str, ...]:
    structured = tuple(
        f"{SEC_FORM13F_STRUCTURED_PREFIX}/{name}" for name in POST_2023_PUBLICATION_ZIPS
    )
    dsi = tuple(f"{SEC_FORM13F_DSI_PREFIX}/{name}" for name in DSI_PUBLICATION_ZIPS)
    return structured + dsi


FORM13F_ZIP_PATHS = historical_quarter_zip_paths() + publication_zip_paths()


def zip_url(relative_path: str) -> str:
    return f"{SEC_FORM13F_BASE_URL}{relative_path}"


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def protocol_payload() -> dict[str, Any]:
    payload = _thaw(EXPERIMENT_PROTOCOL)
    payload["zip_paths"] = list(FORM13F_ZIP_PATHS)
    return payload
