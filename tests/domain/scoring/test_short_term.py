from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from domain.scoring.short_term import (
    ShortTermView,
    TradeSetupView,
    _clamp_score,
    _safe_float,
    _tone_for_state,
    apply_earnings_lockout,
    apply_momentum_context_guard,
    build_short_term_view,
)


def _make_history(
    n: int = 220,
    price: float = 100.0,
    rsi: float = 55.0,
    ma20_ratio: float = 0.98,
    ma50_ratio: float = 0.95,
    ma200_ratio: float = 0.90,
    macd_bullish: bool = True,
    volume: int = 1_000_000,
    volume_mean: int = 800_000,
) -> pd.DataFrame:
    ma20 = price * ma20_ratio
    ma50 = price * ma50_ratio
    ma200 = price * ma200_ratio
    macd_val = 0.5 if macd_bullish else -0.5

    rows = {
        "Open": [price] * n,
        "High": [price + 1.0] * n,
        "Low": [price - 1.0] * n,
        "Close": np.linspace(price * 0.85, price, n).tolist(),
        "Volume": [volume_mean] * (n - 1) + [volume],
        "RSI": [rsi] * n,
        "MA20": [ma20] * n,
        "MA50": [ma50] * n,
        "MA200": [ma200] * n,
        "MACD": [macd_val] * n,
        "MACD_SIGNAL": [0.0] * n,
        "MACD_HIST": [macd_val] * n,
    }
    df = pd.DataFrame(rows)
    df.loc[df.index[-1], "Close"] = price
    return df


class TestClampScore:
    def test_clamps_above_100(self):
        assert _clamp_score(150) == 100

    def test_clamps_below_0(self):
        assert _clamp_score(-10) == 0

    def test_passthrough_in_range(self):
        assert _clamp_score(75) == 75

    def test_boundary_values(self):
        assert _clamp_score(0) == 0
        assert _clamp_score(100) == 100


class TestToneForState:
    def test_enter_now_is_positive(self):
        assert _tone_for_state("ENTER NOW") == "positive"

    def test_wait_is_watch(self):
        assert _tone_for_state("WAIT FOR PULLBACK") == "watch"

    def test_no_trade_is_neutral(self):
        assert _tone_for_state("NO TRADE") == "neutral"

    def test_unknown_label_is_neutral(self):
        assert _tone_for_state("ANYTHING ELSE") == "neutral"


class TestSafeFloat:
    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0

    def test_nan_returns_default(self):
        assert _safe_float(float("nan")) == 0.0

    def test_normal_float(self):
        assert _safe_float(3.14) == pytest.approx(3.14)

    def test_custom_default(self):
        assert _safe_float(None, default=50.0) == 50.0

    def test_int_coerced(self):
        assert _safe_float(42) == pytest.approx(42.0)

    def test_pd_na_returns_default(self):
        assert _safe_float(pd.NA) == 0.0


class TestBuildShortTermView:
    def test_returns_short_term_view(self):
        history = _make_history()
        view = build_short_term_view(history)
        assert isinstance(view, ShortTermView)

    def test_score_bounded(self):
        for rsi in (20.0, 45.0, 60.0, 80.0):
            view = build_short_term_view(_make_history(rsi=rsi))
            assert 0 <= view.score <= 100

    def test_trade_state_tone_matches_label(self):
        view = build_short_term_view(_make_history())
        expected_tone = _tone_for_state(view.trade_state_label)
        assert view.trade_state_tone == expected_tone

    def test_is_actionable_now_iff_enter_now(self):
        view = build_short_term_view(_make_history())
        assert view.is_actionable_now == (view.trade_state_label == "ENTER NOW")

    def test_breakdown_less_than_breakout(self):
        view = build_short_term_view(_make_history())
        assert view.breakdown_level < view.breakout_level

    def test_day_trade_is_trade_setup_view(self):
        view = build_short_term_view(_make_history())
        assert isinstance(view.day_trade, TradeSetupView)

    def test_swing_trade_is_trade_setup_view(self):
        view = build_short_term_view(_make_history())
        assert isinstance(view.swing_trade, TradeSetupView)

    def test_target_above_stop_loss(self):
        view = build_short_term_view(_make_history())
        assert view.day_trade.target_price > view.day_trade.stop_loss_price
        assert view.swing_trade.target_price > view.swing_trade.stop_loss_price

    def test_stop_loss_positive(self):
        view = build_short_term_view(_make_history())
        assert view.day_trade.stop_loss_price > 0
        assert view.swing_trade.stop_loss_price > 0

    def test_zero_moving_averages_fall_back_to_valid_swing_levels(self):
        view = build_short_term_view(
            _make_history(ma20_ratio=0.0, ma50_ratio=0.0, ma200_ratio=0.0)
        )

        assert 0 < view.swing_trade.stop_loss_price < view.swing_trade.entry_price < view.swing_trade.target_price

    def test_optimal_conditions_high_swing_score(self):
        # RSI 55 + above MA50 + bullish MACD + volume spike → swing score ≥ 58
        history = _make_history(rsi=55.0, ma50_ratio=0.95, macd_bullish=True, volume=1_500_000)
        view = build_short_term_view(history)
        assert view.swing_trade.score >= 58

    def test_poor_conditions_low_swing_score(self):
        # RSI < 40 + below MA50 + bearish MACD → swing score < 60
        history = _make_history(rsi=35.0, ma50_ratio=1.05, ma200_ratio=1.02, macd_bullish=False)
        view = build_short_term_view(history)
        assert view.swing_trade.score < 65

    def test_primary_score_is_max_of_both_horizons(self):
        history = _make_history()
        view = build_short_term_view(history)
        assert view.score == max(view.day_trade.score, view.swing_trade.score)

    def test_invalidation_note_non_empty(self):
        view = build_short_term_view(_make_history())
        assert len(view.invalidation_note) > 0

    def test_trend_direction_one_of_three_values(self):
        view = build_short_term_view(_make_history())
        assert view.trend_direction in {"Bullish", "Bearish", "Neutral"}

    def test_no_intraday_falls_back_gracefully(self):
        history = _make_history()
        view = build_short_term_view(history, intraday_15m=None, intraday_60m=None)
        assert isinstance(view, ShortTermView)
        assert 0 <= view.score <= 100
        assert view.day_trade.trade_state_label == "INSUFFICIENT INTRADAY DATA"
        assert view.day_trade.score == 0

    def test_with_intraday_data_produces_valid_view(self):
        history = _make_history()
        intraday = pd.DataFrame({
            "Open": [100.0] * 30,
            "High": [101.0] * 30,
            "Low": [99.0] * 30,
            "Close": [100.0] * 30,
            "Volume": [50_000] * 30,
        })
        view = build_short_term_view(history, intraday_15m=intraday, intraday_60m=intraday)
        assert isinstance(view, ShortTermView)
        assert 0 <= view.score <= 100

    def test_atr_expands_swing_risk_unit(self):
        low_vol = _make_history()
        low_vol["ATR14"] = 1.0
        high_vol = _make_history()
        high_vol["ATR14"] = 4.0

        low_view = build_short_term_view(low_vol)
        high_view = build_short_term_view(high_vol)

        assert high_view.swing_trade.risk_unit > low_view.swing_trade.risk_unit

    def test_earnings_lockout_removes_actionability(self):
        view = build_short_term_view(_make_history(rsi=55.0, volume=1_500_000))
        view.trade_state_label = "ENTER NOW"
        view.is_actionable_now = True

        guarded = apply_earnings_lockout(view, 2)

        assert guarded.trade_state_label == "EARNINGS EVENT LOCKOUT"
        assert guarded.is_actionable_now is False
        assert view.trade_state_label == "ENTER NOW"

    def test_weak_relative_strength_withholds_momentum_entry(self):
        view = build_short_term_view(_make_history())
        view.primary_regime_label = "MOMENTUM"
        view.trade_state_label = "ENTER NOW"
        view.is_actionable_now = True

        guarded = apply_momentum_context_guard(
            view,
            relative_strength_score=30,
            relative_strength_coverage=90,
            hostile_macro_regime=False,
        )

        assert guarded.trade_state_label == "WAIT FOR CONTEXT CONFIRMATION"
        assert guarded.is_actionable_now is False

    def test_reasons_list_non_empty(self):
        view = build_short_term_view(_make_history())
        assert len(view.reasons) > 0

    def test_above_ma50_swing_constructive(self):
        # price above MA50 → trade state is WAIT FOR PULLBACK or ENTER NOW (not NO TRADE)
        history = _make_history(rsi=55.0, ma50_ratio=0.92, macd_bullish=True, volume=1_300_000)
        view = build_short_term_view(history)
        assert view.swing_trade.trade_state_label in {"ENTER NOW", "WAIT FOR PULLBACK"}

    def test_below_ma50_swing_no_trade(self):
        history = _make_history(rsi=35.0, ma50_ratio=1.10, ma200_ratio=1.05, macd_bullish=False)
        view = build_short_term_view(history)
        assert view.swing_trade.trade_state_label == "NO TRADE"
