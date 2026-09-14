from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from config.settings import DATA_DIR


# Frozen before any evaluation. Do not retune cluster N, window, direction,
# role filters, or the code allowlist after seeing results.

OPEN_MARKET_CODES = frozenset({"P", "S"})
DERIVATIVE_TABLE_EXCLUDED = True
ROLE_FILTERS_ENABLED = False

CLUSTER_MIN_INSIDERS = 3
CLUSTER_WINDOW_DAYS = 60
CLUSTER_MIN_INSIDER_VALUE_USD = 10_000.0

STREAK_MIN_CONSECUTIVE_WEEKS = 2
STREAK_MIN_VALUE_USD = 50_000.0

FORWARD_HORIZONS_DAYS = (5, 20, 60)
PRIMARY_HORIZON_DAYS = 20
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 15
MIN_FOLD_EVENTS = 8
REQUIRED_POSITIVE_FOLDS = 2

# Pre-registered overlap threshold X: if more than this share of open-market
# Form-4 accessions already exist in the live SEC events store, treat Section-16
# as enrichment of the existing EDGAR stream rather than a new event stream.
OVERLAP_ENRICHMENT_THRESHOLD_PCT = 70.0
FRESHNESS_SLA_DAYS = 2

SECTION16_MODE = "shadow"
SECTION16_APPLIED_IMPACT = 0
SECTION16_MAX_MODELED_IMPACT = 6
PRIMARY_SOURCE = "sec_insider_transactions_dataset"
SECONDARY_SOURCE = "tracefour"
TRACEFOUR_ENABLED_DEFAULT = False
TRACEFOUR_BASE_URL = "https://tracefour.com"
TRACEFOUR_ANONYMOUS_RATE_LIMIT_PER_HOUR = 60
TRACEFOUR_KEYED_RATE_LIMIT_PER_HOUR = 600
TRACEFOUR_LICENSE = "CC BY 4.0 compilation; underlying Form 4 filings are U.S. government works"
TRACEFOUR_ATTRIBUTION = "Data via Tracefour (https://tracefour.com/filings), CC BY 4.0."

SECTION16_CACHE_DIR = DATA_DIR / "section16_cache"
SECTION16_TRANSACTIONS_FILE = SECTION16_CACHE_DIR / "open_market_transactions.json"
SECTION16_LAST_RUN_FILE = SECTION16_CACHE_DIR / "last_experiment.json"

SEC_INSIDER_DATASET_README_URL = "https://www.sec.gov/files/insider_transactions_readme.pdf"
SEC_INSIDER_DATASET_PAGE_URL = (
    "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
)
SEC_INSIDER_ZIP_URL_TEMPLATE = (
    "https://www.sec.gov/files/structureddata/data/insider-transactions-data-sets/{year}q{quarter}_insider.zip"
)

TRANSACTION_CODE_MAP = MappingProxyType(
    {
        "P": "Open market or private purchase of non-derivative or derivative security.",
        "S": "Open market or private sale of non-derivative or derivative security.",
        "A": "Grant, award, or other acquisition pursuant to Rule 16b-3(d).",
        "C": "Conversion of derivative security.",
        "D": "Disposition to the issuer pursuant to Rule 16b-3(e).",
        "E": "Expiration of short derivative position.",
        "F": "Payment of exercise price or tax liability by delivering or withholding securities.",
        "G": "Bona fide gift.",
        "H": "Expiration or cancellation of long derivative position with value received.",
        "I": "Discretionary transaction in accordance with Rule 16b-3(f).",
        "J": "Other acquisition or disposition (describe in footnote).",
        "L": "Small acquisition under Rule 16a-6.",
        "M": "Exercise or conversion of derivative security exempted pursuant to Rule 16b-3.",
        "O": "Exercise of out-of-the-money derivative security.",
        "U": "Disposition pursuant to a tender of shares in a change of control.",
        "W": "Acquisition or disposition by will or the laws of descent and distribution.",
        "X": "Exercise of in-the-money or at-the-money derivative security.",
        "Z": "Deposit into or withdrawal from voting trust.",
        "K": "Equity swap or similar instrument.",
        "V": "Transaction voluntarily reported earlier than required.",
    }
)

EXCLUDED_CODE_REASONS = MappingProxyType(
    {
        "A": "award_grant",
        "C": "derivative_conversion",
        "D": "disposition_to_issuer",
        "E": "derivative_expiration",
        "F": "tax_or_exercise_withholding",
        "G": "gift",
        "H": "derivative_expiration",
        "I": "rule_16b3_discretionary",
        "J": "other_non_open_market",
        "L": "small_acquisition",
        "M": "derivative_exercise",
        "O": "derivative_exercise",
        "U": "tender_change_of_control",
        "W": "estate_transfer",
        "X": "derivative_exercise",
        "Z": "voting_trust",
        "K": "equity_swap",
        "V": "voluntary_early_report",
    }
)

EXPERIMENT_PROTOCOL = MappingProxyType(
    {
        "hypothesis": (
            "Open-market Section-16 buys (and optionally sells), plus multi-insider "
            "cluster/streak digests, contain calibratable forward-return signal beyond "
            "OmniTrade's existing SEC EDGAR event + earnings intel stack."
        ),
        "mode": SECTION16_MODE,
        "applied_impact": SECTION16_APPLIED_IMPACT,
        "automatic_activation": False,
        "primary_source": PRIMARY_SOURCE,
        "secondary_source": SECONDARY_SOURCE,
        "secondary_source_default_enabled": TRACEFOUR_ENABLED_DEFAULT,
        "open_market_codes": tuple(sorted(OPEN_MARKET_CODES)),
        "transaction_code_map": dict(TRANSACTION_CODE_MAP),
        "excluded_code_reasons": dict(EXCLUDED_CODE_REASONS),
        "exclude_derivative_table": DERIVATIVE_TABLE_EXCLUDED,
        "exclude_identifiable_10b5_1": True,
        "role_filters_enabled": ROLE_FILTERS_ENABLED,
        "cluster_rule": MappingProxyType(
            {
                "source": "tracefour_published_twin",
                "min_distinct_insiders": CLUSTER_MIN_INSIDERS,
                "window_days": CLUSTER_WINDOW_DAYS,
                "same_ticker": True,
                "same_direction": True,
                "min_insider_notional_usd": CLUSTER_MIN_INSIDER_VALUE_USD,
                "open_market_codes_only": True,
            }
        ),
        "streak_rule": MappingProxyType(
            {
                "source": "tracefour_published_twin",
                "min_consecutive_weeks": STREAK_MIN_CONSECUTIVE_WEEKS,
                "min_notional_usd": STREAK_MIN_VALUE_USD,
                "same_owner_ticker_direction": True,
                "open_market_codes_only": True,
            }
        ),
        "primary_metric": (
            f"Spearman IC of net open-market buy dollar intensity vs {PRIMARY_HORIZON_DAYS}d "
            "SPY-excess return"
        ),
        "secondary_metrics": (
            "cluster-flag top-decile hit-rate lift vs EDGAR-event baseline",
            "5d and 60d SPY-excess and sector-excess IC",
        ),
        "success_rule": (
            f"Positive IC or top-decile hit-rate lift vs baseline in "
            f">={REQUIRED_POSITIVE_FOLDS}/{WALK_FORWARD_FOLDS} walk-forward folds; "
            "primary path is SEC; coverage and latency within shadow budget."
        ),
        "fail_rule": (
            "No lift after code filters; OR quarterly lag is stale vs the 2-day Form-4 "
            "freshness SLA without a viable EDGAR XML path; OR overlap with existing "
            f"EDGAR Form-4 events exceeds {OVERLAP_ENRICHMENT_THRESHOLD_PCT:g}% and is "
            "treated as enrichment without incremental nested lift."
        ),
        "overlap_enrichment_threshold_pct": OVERLAP_ENRICHMENT_THRESHOLD_PCT,
        "freshness_sla_days": FRESHNESS_SLA_DAYS,
        "forward_horizons_days": FORWARD_HORIZONS_DAYS,
        "walk_forward_folds": WALK_FORWARD_FOLDS,
        "walk_forward_embargo_days": WALK_FORWARD_EMBARGO_DAYS,
        "tracefour_terms": MappingProxyType(
            {
                "role": "optional_secondary_digest_cross_check",
                "never_primary": True,
                "anonymous_rate_limit_per_hour": TRACEFOUR_ANONYMOUS_RATE_LIMIT_PER_HOUR,
                "keyed_rate_limit_per_hour": TRACEFOUR_KEYED_RATE_LIMIT_PER_HOUR,
                "license": TRACEFOUR_LICENSE,
                "attribution": TRACEFOUR_ATTRIBUTION,
                "docs_url": "https://tracefour.com/api-docs",
            }
        ),
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
