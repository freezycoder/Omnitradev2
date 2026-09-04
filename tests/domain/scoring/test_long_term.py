from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from domain.scoring.long_term import (
    LongTermView,
    _clamp_score,
    _compute_six_month_return,
    build_long_term_view,
)


def _make_history(
    n: int = 220,
    price: float = 100.0,
    ma50_ratio: float = 1.05,
    ma200_ratio: float = 0.90,
    six_month_return: float = 0.15,
) -> pd.DataFrame:
    ma50 = price * ma50_ratio
    ma200 = price * ma200_ratio
    baseline = price / (1 + six_month_return)
    closes = np.linspace(baseline, price, n).tolist()
    return pd.DataFrame({
        "Open": [price] * n,
        "High": [price + 1.0] * n,
        "Low": [price - 1.0] * n,
        "Close": closes,
        "Volume": [1_000_000] * n,
        "MA20": [price * 0.98] * n,
        "MA50": [ma50] * n,
        "MA200": [ma200] * n,
        "RSI": [55.0] * n,
        "MACD": [0.5] * n,
        "MACD_SIGNAL": [0.0] * n,
        "MACD_HIST": [0.5] * n,
    })


def _good_fundamentals() -> dict:
    return {
        "revenueGrowth": 0.15,
        "profitMargins": 0.20,
        "trailingPE": 20.0,
        "debtToEquity": 50.0,
        "returnOnEquity": 0.25,
        "currentRatio": 2.0,
        "earningsGrowth": 0.18,
    }


def _bad_fundamentals() -> dict:
    return {
        "revenueGrowth": -0.05,
        "profitMargins": -0.10,
        "trailingPE": 50.0,
        "debtToEquity": 250.0,
        "returnOnEquity": 0.02,
        "currentRatio": 0.6,
        "earningsGrowth": -0.08,
    }


class TestClampScore:
    def test_clamps_above_100(self):
        assert _clamp_score(150) == 100

    def test_clamps_below_0(self):
        assert _clamp_score(-10) == 0

    def test_passthrough(self):
        assert _clamp_score(60) == 60

    def test_boundaries(self):
        assert _clamp_score(0) == 0
        assert _clamp_score(100) == 100


class TestComputeSixMonthReturn:
    def test_flat_history_returns_zero(self):
        df = _make_history(n=130, six_month_return=0.0)
        result = _compute_six_month_return(df)
        assert abs(result) < 0.01

    def test_rising_history_positive_return(self):
        df = _make_history(n=200, six_month_return=0.20)
        result = _compute_six_month_return(df)
        assert result > 0.10

    def test_empty_history_returns_zero(self):
        assert _compute_six_month_return(pd.DataFrame()) == 0.0

    def test_short_history_uses_first_bar(self):
        closes = list(range(10, 20))
        df = pd.DataFrame({"Close": closes})
        result = _compute_six_month_return(df)
        assert result == pytest.approx((19 / 10) - 1)


class TestBuildLongTermView:
    def test_returns_long_term_view(self):
        view = build_long_term_view(_make_history(), _good_fundamentals())
        assert isinstance(view, LongTermView)

    def test_score_bounded(self):
        for fundamentals in (_good_fundamentals(), _bad_fundamentals(), {}):
            view = build_long_term_view(_make_history(), fundamentals)
            assert 0 <= view.score <= 100

    def test_base_score_is_45(self):
        # No fundamentals, no MA signals, no price history benefit → score near 45 ± adjustments
        history = _make_history(n=220, price=100.0, ma50_ratio=1.0, ma200_ratio=1.01, six_month_return=0.0)
        view = build_long_term_view(history, {})
        # price below MA200 (-8), MA50 not above MA200 (0), 6m return neutral (0) → 45 - 8 = 37
        assert view.score == 37

    def test_above_ma200_adds_15(self):
        # price=100 > MA200=90: +15 (above) + 10 (golden MA50>MA200) = +25 from base
        # price=100 < MA200=110: -8 (below) + 0 (death MA50=105 < MA200=110) = -8 from base
        history_above = _make_history(ma200_ratio=0.90)
        history_below = _make_history(ma200_ratio=1.10)
        view_above = build_long_term_view(history_above, {})
        view_below = build_long_term_view(history_below, {})
        assert view_above.score - view_below.score == 33

    def test_ma50_above_ma200_adds_10(self):
        history_golden = _make_history(ma50_ratio=1.05, ma200_ratio=0.90)   # MA50=105 > MA200=90
        history_death = _make_history(ma50_ratio=0.88, ma200_ratio=0.90)    # MA50=88 < MA200=90
        view_golden = build_long_term_view(history_golden, {})
        view_death = build_long_term_view(history_death, {})
        assert view_golden.score > view_death.score

    def test_good_fundamentals_score_high(self):
        history = _make_history(ma200_ratio=0.90, six_month_return=0.20)
        view = build_long_term_view(history, _good_fundamentals())
        assert view.score >= 75

    def test_bad_fundamentals_score_low(self):
        history = _make_history(ma200_ratio=1.10, six_month_return=-0.15)
        view = build_long_term_view(history, _bad_fundamentals())
        assert view.score <= 35

    def test_high_pe_penalizes(self):
        # Use only PE to avoid score ceiling masking the difference
        fundas_high_pe = {"trailingPE": 45.0}   # -5 points
        fundas_low_pe = {"trailingPE": 20.0}    # +8 points
        history = _make_history()
        view_high = build_long_term_view(history, fundas_high_pe)
        view_low = build_long_term_view(history, fundas_low_pe)
        assert view_low.score > view_high.score

    def test_forward_pe_is_preferred_when_available(self):
        history = _make_history()
        attractive_forward = {"trailingPE": 60.0, "forwardPE": 20.0}
        expensive_forward = {"trailingPE": 20.0, "forwardPE": 60.0}

        assert build_long_term_view(history, attractive_forward).score > build_long_term_view(history, expensive_forward).score

    def test_free_cash_flow_yield_adds_valuation_support(self):
        history = _make_history()
        positive_fcf = {"marketCap": 1_000.0, "freeCashflow": 70.0}
        negative_fcf = {"marketCap": 1_000.0, "freeCashflow": -20.0}

        assert build_long_term_view(history, positive_fcf).score > build_long_term_view(history, negative_fcf).score

    def test_negative_revenue_growth_penalizes(self):
        # Use only revenue growth to avoid score ceiling masking the difference
        fundas_neg = {"revenueGrowth": -0.05}
        fundas_pos = {"revenueGrowth": 0.15}
        history = _make_history()
        assert build_long_term_view(history, fundas_neg).score < build_long_term_view(history, fundas_pos).score

    def test_missing_fundamentals_still_returns_view(self):
        view = build_long_term_view(_make_history(), {})
        assert isinstance(view, LongTermView)
        assert 0 <= view.score <= 100

    def test_strengths_non_empty(self):
        view = build_long_term_view(_make_history(), _good_fundamentals())
        assert len(view.strengths) > 0

    def test_risks_non_empty(self):
        view = build_long_term_view(_make_history(ma200_ratio=1.10), _bad_fundamentals())
        assert len(view.risks) > 0

    def test_thesis_non_empty(self):
        view = build_long_term_view(_make_history(), _good_fundamentals())
        assert len(view.thesis) > 0

    def test_summary_non_empty(self):
        view = build_long_term_view(_make_history(), _good_fundamentals())
        assert len(view.summary) > 0

    def test_news_score_default_50(self):
        view = build_long_term_view(_make_history(), {})
        assert view.news_score == 50

    def test_thesis_references_trend(self):
        view = build_long_term_view(_make_history(ma200_ratio=0.90), {})
        assert "uptrend" in view.thesis or "trend" in view.thesis
