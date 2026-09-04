from __future__ import annotations

import pytest

from domain.scoring.accounting_quality import (
    AccountingQualityView,
    _clamp_score,
    _completeness_confidence,
    _penalty_to_score_impact,
    apply_accounting_overlay,
    build_accounting_quality_view,
)
from domain.scoring.long_term import LongTermView


def _clean_metrics() -> dict:
    return {
        "revenue": [800_000, 1_000_000],
        "net_income": [80_000, 100_000],
        "operating_cash_flow": [110_000, 130_000],
        "free_cash_flow": [90_000, 110_000],
        "receivables": [90_000, 100_000],
        "total_assets": [500_000, 550_000],
        "current_assets": [200_000, 240_000],
        "current_liabilities": [100_000, 110_000],
        "common_shares": [100_000, 100_000],
        "gross_profit": [300_000, 410_000],
        "operating_expense": [680_000, 850_000],
        "goodwill": [20_000, 20_000],
        "intangibles": [10_000, 10_000],
        "total_debt": [100_000, 110_000],
        "special_items": [],
    }


def _make_long_term_view(score: int = 70) -> LongTermView:
    return LongTermView(
        score=score,
        summary="OK",
        strengths=["Good trend"],
        risks=["High PE"],
    )


class TestClampScore:
    def test_above_100(self):
        assert _clamp_score(120) == 100

    def test_below_0(self):
        assert _clamp_score(-5) == 0

    def test_passthrough(self):
        assert _clamp_score(55) == 55


class TestCompletenessConfidence:
    def test_high_confidence(self):
        assert _completeness_confidence(85, 4, 2) == "High"

    def test_moderate_confidence_via_high_checks(self):
        assert _completeness_confidence(65, 2, 1) == "Moderate"

    def test_moderate_confidence_via_medium_checks(self):
        assert _completeness_confidence(65, 1, 3) == "Moderate"

    def test_low_confidence(self):
        assert _completeness_confidence(40, 1, 1) == "Low"

    def test_very_low_confidence(self):
        assert _completeness_confidence(20, 0, 0) == "Very Low"


class TestPenaltyToScoreImpact:
    def test_no_penalty_for_small_points(self):
        assert _penalty_to_score_impact(3) == 0

    def test_small_penalty(self):
        assert _penalty_to_score_impact(6) == 3

    def test_medium_penalty(self):
        assert _penalty_to_score_impact(12) == 6

    def test_large_penalty(self):
        assert _penalty_to_score_impact(24) == 12

    def test_severe_penalty(self):
        assert _penalty_to_score_impact(36) == 18


class TestBuildAccountingQualityView:
    def test_returns_accounting_quality_view(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert isinstance(view, AccountingQualityView)

    def test_clean_data_no_red_flags(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert len(view.red_flags) == 0

    def test_clean_data_high_quality_score(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert view.accounting_quality_score >= 80

    def test_piotroski_score_uses_available_statement_checks(self):
        view = build_accounting_quality_view({}, _clean_metrics())

        assert view.piotroski_available_checks == 9
        assert view.piotroski_score is not None
        assert view.piotroski_label in {"Strong", "Mixed", "Weak"}

    def test_strong_piotroski_adds_long_term_quality_adjustment(self):
        view = build_accounting_quality_view({}, _clean_metrics())

        assert view.piotroski_score >= 7
        assert view.long_term_score_adjustment == 4

    def test_score_bounded(self):
        for metrics in (_clean_metrics(), None, {}):
            view = build_accounting_quality_view({}, metrics)
            assert 0 <= view.accounting_quality_score <= 100
            assert 0 <= view.shenanigan_risk_score <= 100

    def test_shenanigan_plus_quality_roughly_100(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        # shenanigan = 100 - quality + flag_bonus, so quality + shenanigan >= 100 (can exceed due to flag bonus)
        assert view.shenanigan_risk_score >= 100 - view.accounting_quality_score

    def test_empty_metrics_limited_data_penalty(self):
        view = build_accounting_quality_view({}, None)
        assert view.accounting_quality_score <= 95  # limited data penalty applied
        assert view.accounting_data_completeness_score == 0

    def test_bad_cash_conversion_adds_red_flag(self):
        metrics = dict(_clean_metrics())
        # OCF negative while net_income positive → cash conversion penalty
        metrics["operating_cash_flow"] = [-50_000, -80_000]
        view = build_accounting_quality_view({}, metrics)
        assert len(view.red_flags) > 0

    def test_receivables_growing_faster_than_revenue_adds_flag(self):
        metrics = dict(_clean_metrics())
        metrics["revenue"] = [1_000_000, 1_050_000]        # 5% revenue growth
        metrics["receivables"] = [50_000, 120_000]          # 140% receivables growth
        view = build_accounting_quality_view({}, metrics)
        assert len(view.red_flags) > 0

    def test_label_is_string(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert isinstance(view.label, str)
        assert len(view.label) > 0

    def test_explanation_is_string(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert isinstance(view.explanation, str)

    def test_completeness_score_bounded(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert 0 <= view.accounting_data_completeness_score <= 100

    def test_confidence_is_one_of_four_levels(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert view.accounting_assessment_confidence in {"High", "Moderate", "Low", "Very Low"}

    def test_penalty_points_non_negative(self):
        view = build_accounting_quality_view({}, _clean_metrics())
        assert view.penalty_points >= 0

    def test_debt_to_equity_overlay_high_leverage_extra_penalty(self):
        # High D/E + existing penalty_points >= 12 triggers extra -6
        metrics = dict(_clean_metrics())
        metrics["operating_cash_flow"] = [-50_000, -80_000]  # triggers cash conversion (-16)
        metrics["free_cash_flow"] = [-30_000, -40_000]        # triggers FCF (-12)
        fundamentals = {"debtToEquity": 300.0}
        view = build_accounting_quality_view(fundamentals, metrics)
        assert view.accounting_quality_score < 80


class TestApplyAccountingOverlay:
    def test_no_penalty_no_flags_returns_same_view(self):
        lt_view = _make_long_term_view(score=70)
        aq_view = build_accounting_quality_view({}, _clean_metrics())
        if (
            aq_view.long_term_score_penalty == 0
            and aq_view.long_term_score_adjustment == 0
            and not aq_view.red_flags
        ):
            result = apply_accounting_overlay(lt_view, aq_view)
            assert result.score == lt_view.score

    def test_penalty_reduces_long_term_score(self):
        lt_view = _make_long_term_view(score=80)
        # Manufacture an accounting view with a known penalty
        metrics = dict(_clean_metrics())
        metrics["operating_cash_flow"] = [-50_000, -80_000]  # severe penalty
        aq_view = build_accounting_quality_view({}, metrics)
        result = apply_accounting_overlay(lt_view, aq_view)
        assert result.score <= lt_view.score

    def test_overlay_adds_accounting_risk_to_risks(self):
        lt_view = _make_long_term_view(score=70)
        metrics = dict(_clean_metrics())
        metrics["operating_cash_flow"] = [-50_000, -80_000]
        aq_view = build_accounting_quality_view({}, metrics)
        if aq_view.red_flags:
            result = apply_accounting_overlay(lt_view, aq_view)
            assert any("Accounting quality warning" in r for r in result.risks)

    def test_result_score_clamped(self):
        lt_view = _make_long_term_view(score=5)
        metrics = dict(_clean_metrics())
        metrics["operating_cash_flow"] = [-50_000, -80_000]
        aq_view = build_accounting_quality_view({}, metrics)
        result = apply_accounting_overlay(lt_view, aq_view)
        assert result.score >= 0

    def test_original_view_not_mutated(self):
        lt_view = _make_long_term_view(score=70)
        original_score = lt_view.score
        metrics = dict(_clean_metrics())
        metrics["operating_cash_flow"] = [-50_000, -80_000]
        aq_view = build_accounting_quality_view({}, metrics)
        apply_accounting_overlay(lt_view, aq_view)
        assert lt_view.score == original_score
