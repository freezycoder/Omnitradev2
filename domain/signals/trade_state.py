from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TradeStateThresholds:
    lookback_period: int = 20
    watch_proximity_pct: float = 1.0
    confirm_break_pct: float = 0.75
    volume_confirmation_ratio: float = 1.15


@dataclass(frozen=True)
class TradeState:
    label: str
    tone: str
    breakout_level: float
    breakdown_level: float
    explanation: str
    is_actionable: bool


TRADE_STATE_THRESHOLDS = TradeStateThresholds()


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def evaluate_trade_state(history: pd.DataFrame) -> TradeState:
    latest = history.iloc[-1]
    prior_window = history.iloc[:-1].tail(TRADE_STATE_THRESHOLDS.lookback_period)
    if prior_window.empty:
        prior_window = history.tail(TRADE_STATE_THRESHOLDS.lookback_period + 1).iloc[:-1]

    breakout_level = float(prior_window["High"].max()) if not prior_window.empty else float(latest["High"])
    breakdown_level = float(prior_window["Low"].min()) if not prior_window.empty else float(latest["Low"])

    current_close = float(latest["Close"])
    previous_close = float(history.iloc[-2]["Close"]) if len(history) >= 2 else current_close
    volume_average = float(history["Volume"].tail(20).mean()) if history["Volume"].tail(20).mean() else 0.0
    volume_ratio = _safe_ratio(float(latest["Volume"]), volume_average) if volume_average else 1.0

    near_breakout = current_close >= breakout_level * (1 - TRADE_STATE_THRESHOLDS.watch_proximity_pct / 100)
    near_breakdown = current_close <= breakdown_level * (1 + TRADE_STATE_THRESHOLDS.watch_proximity_pct / 100)
    confirmed_breakout = (
        current_close >= breakout_level * (1 + TRADE_STATE_THRESHOLDS.confirm_break_pct / 100)
        and (volume_ratio >= TRADE_STATE_THRESHOLDS.volume_confirmation_ratio or previous_close > breakout_level)
        and float(latest["MACD"]) > float(latest["MACD_SIGNAL"])
        and float(latest["MA20"]) >= float(latest["MA50"])
    )
    confirmed_breakdown = (
        current_close <= breakdown_level * (1 - TRADE_STATE_THRESHOLDS.confirm_break_pct / 100)
        and (volume_ratio >= TRADE_STATE_THRESHOLDS.volume_confirmation_ratio or previous_close < breakdown_level)
        and float(latest["MACD"]) < float(latest["MACD_SIGNAL"])
        and float(latest["MA20"]) <= float(latest["MA50"])
    )

    if confirmed_breakout:
        return TradeState(
            label="CONFIRMED BREAKOUT — BUY",
            tone="positive",
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
            explanation="Breakout confirmed above resistance with trend and momentum support; bullish continuation setup is active.",
            is_actionable=True,
        )
    if confirmed_breakdown:
        return TradeState(
            label="CONFIRMED BREAKDOWN — SELL",
            tone="negative",
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
            explanation="Breakdown confirmed below support with bearish confirmation; avoid long exposure or treat as a bearish setup.",
            is_actionable=True,
        )
    if near_breakout and current_close < breakout_level * (1 + TRADE_STATE_THRESHOLDS.confirm_break_pct / 100):
        return TradeState(
            label="BREAKOUT WATCH",
            tone="watch",
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
            explanation="Price is testing resistance; wait for a decisive close beyond the breakout level before treating it as tradable.",
            is_actionable=False,
        )
    if near_breakdown and current_close > breakdown_level * (1 - TRADE_STATE_THRESHOLDS.confirm_break_pct / 100):
        return TradeState(
            label="BREAKDOWN WATCH",
            tone="watch",
            breakout_level=breakout_level,
            breakdown_level=breakdown_level,
            explanation="Price is leaning on support; wait for a decisive breakdown before treating it as a confirmed downside setup.",
            is_actionable=False,
        )
    return TradeState(
        label="NO TRADE — RANGE",
        tone="neutral",
        breakout_level=breakout_level,
        breakdown_level=breakdown_level,
        explanation="Price remains inside the recent range without confirmation; there is no active short-term trade yet.",
        is_actionable=False,
    )
