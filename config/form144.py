from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from config.settings import DATA_DIR, SEC_ARCHIVES_BASE_URL, SEC_EDGAR_BASE_URL


# Frozen before any evaluation. Do not retune cluster N/W, match window T,
# the affiliate filter, or the match-rate floor after seeing results.

COVERAGE_START = "2022-10-01"
XML_SPEC_VERSION = "2.0"
XML_SPEC_DATE = "2022-10-17"

CLUSTER_MIN_AFFILIATES = 3
CLUSTER_WINDOW_DAYS = 5
MATCH_WINDOW_DAYS = 10
MATCH_RATE_FLOOR = 0.40
MIN_ELIGIBLE_NOTICES = 20
MIN_FOLD_NOTICES = 6
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 15
REQUIRED_POSITIVE_FOLDS = 2
FORM4_LOOKBACK_DAYS = 5
NESTED_LIFT_EPSILON = 1e-12
OPTIONAL_DRIFT_HORIZONS_DAYS = (5, 20)
PRIMARY_DRIFT_HORIZON_DAYS = 5

FORM4_SALE_CODES = frozenset({"S"})
FORM4_SALE_ACQUIRED_DISPOSED = "D"

FORM144_MODE = "shadow"
FORM144_APPLIED_IMPACT = 0
FORM144_MODELED_IMPACT = 0
PRIMARY_SOURCE = "edgar_form144_xml"
FORM4_KEEP_SOURCE = "section16_open_market_transactions"
FORM4_KEEP_RELATIVE_PATH = "section16_cache/open_market_transactions.json"

FORM144_CACHE_DIR = DATA_DIR / "form144_cache"
FORM144_NOTICES_FILE = FORM144_CACHE_DIR / "proposed_sales.json"
FORM144_LAST_RUN_FILE = FORM144_CACHE_DIR / "last_experiment.json"
FORM4_KEEP_CANDIDATE_FILE = DATA_DIR / FORM4_KEEP_RELATIVE_PATH

SEC_FORM144_GUIDE_URL = (
    "https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/"
    "file-form-144-electronically"
)
SEC_FORM144_SPEC_PAGE_URL = "https://www.sec.gov/submit-filings/technical-specifications"
SEC_EDGAR_SEARCH_URL = "https://www.sec.gov/edgar/search/"

AFFILIATE_FILTER = MappingProxyType(
    {
        "require_filer_cik": True,
        "require_issuer_cik": True,
        "exclude_filer_equals_issuer": True,
        "officer_director_flag": "not_on_form144_xml",
        "notes": (
            "Form 144 identifies the reporting person by filer CIK. Unlike Form 4, "
            "the XML does not carry isDirector/isOfficer flags. Affiliates are the "
            "filer CIK distinct from the issuer CIK after the electronic-mandate window."
        ),
    }
)

EXPERIMENT_PROTOCOL = MappingProxyType(
    {
        "hypothesis": (
            "Form 144 notices of proposed sale of restricted/control securities "
            "provide an earlier intent signal than executed Form 4 sales; ticker-level "
            "144 clusters and 144→Form4 match/conflict improve shadow insider-sale "
            "calibration beyond Form4-only."
        ),
        "falsifier": (
            "Match rate of Form 144 → subsequent Form 4 sale within the "
            "pre-registered window is too low to be useful; OR 144 features add no "
            "incremental information vs Form4-only sell intensity in walk-forward."
        ),
        "mode": FORM144_MODE,
        "applied_impact": FORM144_APPLIED_IMPACT,
        "modeled_impact": FORM144_MODELED_IMPACT,
        "automatic_activation": False,
        "live_recommendation_changes": False,
        "alpha_claim": False,
        "jof_car_claim": False,
        "primary_source": PRIMARY_SOURCE,
        "coverage_start": COVERAGE_START,
        "xml_spec_version": XML_SPEC_VERSION,
        "xml_spec_date": XML_SPEC_DATE,
        "cluster_rule": MappingProxyType(
            {
                "min_distinct_affiliates": CLUSTER_MIN_AFFILIATES,
                "window_days": CLUSTER_WINDOW_DAYS,
                "same_ticker": True,
                "affiliate_filter": dict(AFFILIATE_FILTER),
                "frozen": True,
            }
        ),
        "match_study": MappingProxyType(
            {
                "form4_codes": tuple(sorted(FORM4_SALE_CODES)),
                "acquired_disposed": FORM4_SALE_ACQUIRED_DISPOSED,
                "window_days": MATCH_WINDOW_DAYS,
                "floor": MATCH_RATE_FLOOR,
                "join": "issuer_cik + filer_cik, fallback ticker-level",
                "same_day_counts_as_match": True,
            }
        ),
        "nested_model": MappingProxyType(
            {
                "baseline": "form4_sell_intensity",
                "nested": (
                    "unmatched_144_intensity",
                    "cluster_144",
                    "prior_3m_units",
                ),
                "target": "subsequent_form4_sale_within_T",
                "walk_forward_folds": WALK_FORWARD_FOLDS,
                "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
                "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
                "metric": "held_out_mse_reduction_vs_form4_only",
            }
        ),
        "secondary_only": MappingProxyType(
            {
                "optional_post_144_drift": True,
                "horizons_days": OPTIONAL_DRIFT_HORIZONS_DAYS,
                "label": "descriptive_only_not_car_not_alpha",
            }
        ),
        "success_rule": (
            f"Match rate >= {MATCH_RATE_FLOOR:.0%} AND nested Form4-sale prediction "
            f"lift in >={REQUIRED_POSITIVE_FOLDS}/{WALK_FORWARD_FOLDS} folds; OR match "
            "study alone justifies keeping 144 as conflict radar with return lift "
            "null, reclassified as infra (not alpha) for a human call."
        ),
        "fail_rule": (
            "Structured feed too thin; match rate below the pre-registered floor; "
            "or no incremental information vs Form4-only sell intensity."
        ),
        "overfitting_mitigations": (
            "do_not_treat_all_144s_as_bearish",
            "cluster_n_w_frozen",
            "affiliate_filter_documented",
            "primary_metric_is_match_rate_plus_nested_form4_test",
            "no_jof_car_claim",
        ),
        "sec_guide": SEC_FORM144_GUIDE_URL,
        "sec_spec_page": SEC_FORM144_SPEC_PAGE_URL,
        "edgar_search": SEC_EDGAR_SEARCH_URL,
        "sec_edgar_base_url": SEC_EDGAR_BASE_URL,
        "sec_archives_base_url": SEC_ARCHIVES_BASE_URL,
        "form4_keep_relative_path": FORM4_KEEP_RELATIVE_PATH,
    }
)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def protocol_payload() -> dict[str, Any]:
    return _thaw(EXPERIMENT_PROTOCOL)
