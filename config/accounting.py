from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccountingThresholds:
    base_quality_score: int = 100
    limited_data_penalty: int = 5
    cash_conversion_warning: float = 0.85
    cash_conversion_severe: float = 0.60
    fcf_conversion_warning: float = 0.75
    fcf_conversion_severe: float = 0.45
    receivables_growth_gap_warning: float = 0.08
    receivables_growth_gap_severe: float = 0.20
    dso_growth_warning: float = 0.08
    dso_growth_severe: float = 0.18
    asset_growth_gap_warning: float = 0.15
    asset_growth_gap_severe: float = 0.30
    goodwill_asset_ratio_warning: float = 0.20
    goodwill_asset_ratio_severe: float = 0.35
    acquisition_growth_gap_warning: float = 0.15
    acquisition_growth_gap_severe: float = 0.30
    repeated_special_items_count: int = 2
    special_items_materiality_ratio: float = 0.03
    debt_growth_gap_warning: float = 0.15
    debt_growth_gap_severe: float = 0.30
    debt_to_ocf_warning: float = 4.0
    debt_to_ocf_severe: float = 6.0
    short_term_warning_risk_threshold: int = 55
    limited_visibility_threshold: int = 35
    inconclusive_threshold: int = 55
    clean_reporting_min_completeness: int = 75
    generally_acceptable_min_completeness: int = 55
    low_confidence_penalty_steps: int = 1
    very_low_confidence_penalty_steps: int = 2


ACCOUNTING_THRESHOLDS = AccountingThresholds()

ACCOUNTING_LABEL_RULES = (
    (85, "Clean Reporting"),
    (70, "Generally Acceptable"),
    (50, "Elevated Shenanigan Risk"),
    (0, "Serious Earnings Quality Warning"),
)

ACCOUNTING_RECOMMENDATION_CAPS = (
    (80, "Avoid", 2),
    (65, "Hold", 1),
    (50, "Buy", 1),
)

__all__ = [
    "ACCOUNTING_LABEL_RULES",
    "ACCOUNTING_RECOMMENDATION_CAPS",
    "ACCOUNTING_THRESHOLDS",
    "AccountingThresholds",
]
