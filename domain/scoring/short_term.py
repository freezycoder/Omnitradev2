from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

import pandas as pd

from domain.signals.trade_levels import INVALID_TRADE_LEVEL_STATE, validate_long_trade_levels
from domain.technical.indicators import compute_atr, compute_rsi


REGIME_MOMENTUM = "MOMENTUM"
REGIME_MEAN_REVERSION = "MEAN_REVERSION"


@dataclass(frozen=True)
class RegimeScore:
    label: str
    score: int
    aligned: bool
    setup_type: str
    explanation: str
    reasons: list[str]


@dataclass
class TradeSetupView:
    horizon_label: str
    score: int
    trade_state_label: str
    trade_state_tone: str
    holding_period_label: str
    setup_type: str
    entry_price: float
    target_price: float
    stop_loss_price: float
    explanation: str
    reasons: list[str] = field(default_factory=list)
    regime_label: str = REGIME_MOMENTUM
    regime_scores: dict[str, int] = field(default_factory=dict)
    ranking_bucket: str = ""
    data_quality: str = "complete"
    risk_unit: float | None = None


@dataclass
class ShortTermView:
    score: int
    trend_direction: str
    trade_state_label: str
    trade_state_tone: str
    trade_state_explanation: str
    breakout_level: float
    breakdown_level: float
    is_actionable_now: bool
    setup_type: str
    expected_holding_period: str
    entry_idea: str
    stop_loss_idea: str
    target_idea: str
    day_trade: TradeSetupView
    swing_trade: TradeSetupView
    primary_horizon_label: str
    primary_regime_label: str = REGIME_MOMENTUM
    primary_ranking_bucket: str = ""
    regime_scores: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    invalidation_note: str = ""
    news_score: int = 50
    news_impact: int = 0
    news_summary: str = ""
    news_signals: list[str] = field(default_factory=list)


def _clamp_score(score: int) -> int:
    return max(0, min(100, score))


def _tone_for_state(label: str) -> str:
    if label == "ENTER NOW":
        return "positive"
    if label == "WAIT FOR PULLBACK":
        return "watch"
    return "neutral"


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def _positive_float(value, default: float) -> float:
    number = _safe_float(value, default)
    return number if number > 0 else default


def _enforce_trade_setup_levels(view: TradeSetupView, reference_price: float) -> TradeSetupView:
    validation = validate_long_trade_levels(
        entry_price=view.entry_price,
        target_price=view.target_price,
        stop_loss_price=view.stop_loss_price,
        reference_price=reference_price,
    )
    if validation.valid:
        return view
    view.trade_state_label = INVALID_TRADE_LEVEL_STATE
    view.trade_state_tone = "negative"
    view.explanation = validation.reason or "Trade levels failed validation."
    return view


def _derive_intraday_metrics(
    history: pd.DataFrame,
    intraday_15m: pd.DataFrame | None,
    intraday_60m: pd.DataFrame | None,
) -> dict[str, float]:
    latest_daily = history.iloc[-1]
    current_price = _positive_float(latest_daily["Close"], 0.01)
    daily_rsi = _safe_float(latest_daily.get("RSI"), 50.0)
    daily_volume_ratio = _safe_float(latest_daily.get("Volume")) / max(_safe_float(history["Volume"].tail(20).mean(), 1.0), 1.0)
    vwap_deviation_pct = ((_safe_float(latest_daily["Close"]) / max(_safe_float(latest_daily.get("MA20"), current_price), 1.0)) - 1) * 100

    metrics = {
        "rsi_15m": daily_rsi,
        "rsi_1h": daily_rsi,
        "vwap_deviation_pct": vwap_deviation_pct,
        "volume_spike_ratio": max(daily_volume_ratio, 1.0),
        "current_price": current_price,
    }

    if intraday_15m is not None and not intraday_15m.empty:
        bars_15m = intraday_15m.copy()
        bars_15m["RSI"] = compute_rsi(bars_15m["Close"])
        session = bars_15m.tail(min(len(bars_15m), 30)).copy()
        typical_price = (session["High"] + session["Low"] + session["Close"]) / 3
        cumulative_vwap = (typical_price * session["Volume"]).cumsum() / session["Volume"].replace(0, pd.NA).cumsum()
        last_vwap = _safe_float(cumulative_vwap.iloc[-1], current_price)
        avg_bar_volume = _safe_float(session["Volume"].tail(20).mean(), 1.0)
        last_bar_volume = _safe_float(session["Volume"].iloc[-1], avg_bar_volume)
        metrics["rsi_15m"] = _safe_float(session["RSI"].iloc[-1], metrics["rsi_15m"])
        metrics["volume_spike_ratio"] = last_bar_volume / max(avg_bar_volume, 1.0)
        metrics["current_price"] = _positive_float(session["Close"].iloc[-1], current_price)
        metrics["vwap_deviation_pct"] = ((metrics["current_price"] / max(last_vwap, 1.0)) - 1) * 100

    if intraday_60m is not None and not intraday_60m.empty:
        bars_60m = intraday_60m.copy()
        bars_60m["RSI"] = compute_rsi(bars_60m["Close"])
        metrics["rsi_1h"] = _safe_float(bars_60m["RSI"].iloc[-1], metrics["rsi_1h"])

    return metrics


def _latest_trend_flags(history: pd.DataFrame, current_price: float) -> dict[str, bool | float]:
    latest = history.iloc[-1]
    ma20 = _positive_float(latest.get("MA20"), current_price)
    ma50 = _positive_float(latest.get("MA50"), current_price)
    ma200 = _positive_float(latest.get("MA200"), current_price)
    return {
        "ma20": ma20,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma20": current_price > ma20,
        "above_ma50": current_price > ma50,
        "above_ma200": current_price > ma200,
        "ma50_above_ma200": ma50 > ma200,
    }


def _pick_regime(momentum: RegimeScore, mean_reversion: RegimeScore) -> RegimeScore:
    # Momentum wins ties so the historical default behavior remains stable.
    if mean_reversion.score > momentum.score:
        return mean_reversion
    return momentum


def _score_day_momentum(metrics: dict[str, float], trend: dict[str, bool | float]) -> RegimeScore:
    score = 42
    reasons: list[str] = []
    rsi_15m = metrics["rsi_15m"]
    rsi_1h = metrics["rsi_1h"]
    vwap_dev = metrics["vwap_deviation_pct"]
    volume_spike = metrics["volume_spike_ratio"]

    if 45 <= rsi_15m <= 62:
        score += 12
        reasons.append("15-minute RSI is supportive without being overextended.")
    elif 38 <= rsi_15m < 45 or 62 < rsi_15m <= 72:
        score += 6
        reasons.append("15-minute RSI is directional, but the intraday move is not perfectly balanced.")
    else:
        score -= 10
        reasons.append("15-minute RSI is stretched, which raises fade risk for a 1-2 day trade.")

    if 48 <= rsi_1h <= 65:
        score += 14
        reasons.append("1-hour RSI supports follow-through on the current intraday trend.")
    elif rsi_1h >= 40:
        score += 6
        reasons.append("1-hour RSI is constructive but not yet strong enough for maximum conviction.")
    else:
        score -= 10
        reasons.append("1-hour RSI is weak, which limits short-horizon trade quality.")

    if 0 <= vwap_dev <= 1.5:
        score += 14
        reasons.append("Price is holding just above VWAP, which supports immediate execution.")
    elif -0.4 <= vwap_dev < 0 or 1.5 < vwap_dev <= 3:
        score += 5
        reasons.append("Price is near VWAP, so a cleaner entry may come on a small pullback.")
    else:
        score -= 8
        reasons.append("Price is too far from VWAP, which makes the intraday location less attractive.")

    if volume_spike >= 1.8:
        score += 12
        reasons.append("Intraday volume is spiking, which improves confirmation for a fast trade.")
    elif volume_spike >= 1.2:
        score += 6
        reasons.append("Intraday volume is above baseline, which helps the setup.")
    else:
        score -= 6
        reasons.append("Intraday volume is quiet, so the move may not have enough urgency.")

    if bool(trend["above_ma20"]) and bool(trend["above_ma50"]):
        score += 4
        reasons.append("Price is above MA20 and MA50, keeping the fast setup trend-following.")
    elif not bool(trend["above_ma50"]):
        score -= 4
        reasons.append("Price is below MA50, which makes pure momentum less reliable.")

    aligned = rsi_15m >= 50 and rsi_1h >= 50 and vwap_dev >= 0 and volume_spike >= 1.2
    return RegimeScore(
        label=REGIME_MOMENTUM,
        score=_clamp_score(int(round(score))),
        aligned=aligned,
        setup_type="Intraday momentum / VWAP",
        explanation="Intraday momentum, VWAP location, and volume are aligned for an immediate 1-2 day entry.",
        reasons=reasons,
    )


def _score_day_mean_reversion(metrics: dict[str, float], trend: dict[str, bool | float]) -> RegimeScore:
    score = 38
    reasons: list[str] = []
    rsi_15m = metrics["rsi_15m"]
    rsi_1h = metrics["rsi_1h"]
    vwap_dev = metrics["vwap_deviation_pct"]
    volume_spike = metrics["volume_spike_ratio"]

    if bool(trend["above_ma200"]):
        score += 14
        reasons.append("The daily trend is above MA200, so a pullback can be treated as mean reversion instead of trend damage.")
    else:
        score -= 10
        reasons.append("The daily trend is below MA200, so oversold readings carry more downside risk.")

    if bool(trend["ma50_above_ma200"]):
        score += 8
        reasons.append("MA50 remains above MA200, which supports buying weakness inside a larger uptrend.")

    if rsi_15m <= 35:
        score += 14
        reasons.append("15-minute RSI is oversold enough to support a snapback setup.")
    elif rsi_15m <= 45:
        score += 8
        reasons.append("15-minute RSI is pulling back into a potential reset zone.")
    else:
        score -= 6
        reasons.append("15-minute RSI is not washed out enough for a clean mean-reversion entry.")

    if rsi_1h <= 42:
        score += 12
        reasons.append("1-hour RSI is also soft, giving the pullback room to revert.")
    elif rsi_1h <= 50:
        score += 6
        reasons.append("1-hour RSI is cooling without fully breaking the setup.")
    else:
        score -= 4
        reasons.append("1-hour RSI is not yet reset, so the pullback may be shallow.")

    if -3.0 <= vwap_dev <= 0.5:
        score += 12
        reasons.append("Price is below or near VWAP, which gives the bounce setup a logical entry zone.")
    elif -5.0 <= vwap_dev < -3.0:
        score += 4
        reasons.append("Price is washed out below VWAP, but the move may need stabilization first.")
    else:
        score -= 8
        reasons.append("Price location is not close enough to VWAP for a disciplined mean-reversion entry.")

    if 0.8 <= volume_spike <= 1.8:
        score += 5
        reasons.append("Volume is active without looking like panic liquidation.")
    elif volume_spike > 2.5:
        score -= 6
        reasons.append("Volume is extreme, which can mean forced selling rather than a simple pullback.")

    aligned = bool(trend["above_ma200"]) and rsi_15m <= 45 and rsi_1h <= 50 and -3.5 <= vwap_dev <= 0.75
    return RegimeScore(
        label=REGIME_MEAN_REVERSION,
        score=_clamp_score(int(round(score))),
        aligned=aligned,
        setup_type="Mean-reversion pullback / VWAP",
        explanation="The larger trend is constructive while intraday RSI and VWAP location show a pullback entry.",
        reasons=reasons,
    )


def _build_day_trade_view(
    history: pd.DataFrame,
    intraday_15m: pd.DataFrame | None,
    intraday_60m: pd.DataFrame | None,
) -> TradeSetupView:
    latest = history.iloc[-1]
    metrics = _derive_intraday_metrics(history, intraday_15m, intraday_60m)
    current_price = metrics["current_price"]
    has_intraday_15m = intraday_15m is not None and not intraday_15m.empty
    has_intraday_60m = intraday_60m is not None and not intraday_60m.empty
    if not (has_intraday_15m and has_intraday_60m):
        atr = _positive_float(latest.get("ATR14"), current_price * 0.015)
        risk_unit = max(atr, current_price * 0.005)
        entry_price = current_price
        stop_loss = max(entry_price - risk_unit, 0.01)
        target_price = entry_price + 1.8 * risk_unit
        return _enforce_trade_setup_levels(TradeSetupView(
            horizon_label="1-2 Day Trade",
            score=0,
            trade_state_label="INSUFFICIENT INTRADAY DATA",
            trade_state_tone="neutral",
            holding_period_label="1-2 Days",
            setup_type="Intraday data unavailable",
            entry_price=round(entry_price, 2),
            target_price=round(target_price, 2),
            stop_loss_price=round(stop_loss, 2),
            explanation="Both 15-minute and 1-hour bars are required; daily indicators are not substituted for intraday evidence.",
            reasons=["Intraday coverage is incomplete, so the fast setup is withheld instead of estimated from daily bars."],
            ranking_bucket="1-2 Day Trade:UNAVAILABLE",
            data_quality="insufficient_intraday",
            risk_unit=round(risk_unit, 4),
        ), current_price)
    trend = _latest_trend_flags(history, current_price)
    momentum = _score_day_momentum(metrics, trend)
    mean_reversion = _score_day_mean_reversion(metrics, trend)
    selected = _pick_regime(momentum, mean_reversion)
    vwap_dev = metrics["vwap_deviation_pct"]

    if selected.label == REGIME_MOMENTUM and selected.score >= 72 and selected.aligned and abs(vwap_dev) <= 1.5:
        trade_state = "ENTER NOW"
        explanation = selected.explanation
    elif selected.label == REGIME_MEAN_REVERSION and selected.score >= 72 and selected.aligned:
        trade_state = "ENTER NOW"
        explanation = selected.explanation
    elif selected.score >= 58 and selected.aligned:
        trade_state = "WAIT FOR PULLBACK"
        explanation = (
            "The setup is constructive, but the best risk/reward likely comes from a cleaner entry near the planned pullback zone."
        )
    else:
        trade_state = "NO TRADE"
        explanation = "The intraday setup lacks enough alignment for the selected short-term regime."

    vwap_anchor = current_price / (1 + (vwap_dev / 100)) if current_price else _safe_float(latest["Close"])
    latest_low = _positive_float(latest["Low"], current_price)
    day_low = _positive_float(intraday_15m["Low"].tail(12).min(), latest_low) if intraday_15m is not None and not intraday_15m.empty else latest_low
    intraday_atr = _positive_float(compute_atr(intraday_15m).iloc[-1], current_price * 0.008)
    daily_atr = _positive_float(latest.get("ATR14"), intraday_atr)
    risk_buffer = max(
        intraday_atr * (1.0 if selected.label == REGIME_MEAN_REVERSION else 1.5),
        min(daily_atr, current_price * 0.03) * 0.35,
        current_price * 0.003,
    )

    if trade_state == "ENTER NOW":
        entry_price = current_price
    else:
        entry_price = min(current_price, vwap_anchor * 1.003)

    stop_loss = max(min(day_low, entry_price - risk_buffer), 0.01)
    target_price = max(entry_price + 1.8 * max(entry_price - stop_loss, risk_buffer), entry_price + risk_buffer)

    return _enforce_trade_setup_levels(TradeSetupView(
        horizon_label="1-2 Day Trade",
        score=selected.score,
        trade_state_label=trade_state,
        trade_state_tone=_tone_for_state(trade_state),
        holding_period_label="1-2 Days",
        setup_type=selected.setup_type,
        entry_price=round(entry_price, 2),
        target_price=round(target_price, 2),
        stop_loss_price=round(stop_loss, 2),
        explanation=explanation,
        reasons=selected.reasons,
        regime_label=selected.label,
        regime_scores={
            REGIME_MOMENTUM: momentum.score,
            REGIME_MEAN_REVERSION: mean_reversion.score,
        },
        ranking_bucket=f"1-2 Day Trade:{selected.label}",
        risk_unit=round(risk_buffer, 4),
    ), current_price)


def _score_swing_momentum(
    *,
    daily_rsi: float,
    volume_ratio: float,
    close_above_ma20: bool,
    close_above_ma50: bool,
    macd_bullish: bool,
) -> tuple[RegimeScore, str]:
    score = 40
    reasons: list[str] = []

    if 48 <= daily_rsi <= 65:
        score += 15
        reasons.append("Daily RSI is in a healthy range for a swing continuation.")
    elif 40 <= daily_rsi < 48 or 65 < daily_rsi <= 72:
        score += 7
        reasons.append("Daily RSI is supportive, but the setup is not perfectly balanced.")
    else:
        score -= 8
        reasons.append("Daily RSI is either weak or overextended for a clean swing setup.")

    if close_above_ma50:
        score += 18
        reasons.append("Price is above the 50-day moving average, which keeps the swing structure constructive.")
    else:
        score -= 12
        reasons.append("Price is below the 50-day moving average, which weakens the 5-15 day setup.")

    if volume_ratio >= 1.3:
        score += 10
        reasons.append("Daily volume is expanding, which improves breakout or continuation odds.")
    elif volume_ratio >= 1.05:
        score += 5
        reasons.append("Daily volume is modestly supportive.")
    else:
        score -= 5
        reasons.append("Daily volume is muted, so momentum confirmation is weaker.")

    if close_above_ma20 and close_above_ma50 and macd_bullish:
        score += 16
        trend_direction = "Bullish"
        reasons.append("Momentum trend is constructive with price above the key moving averages and MACD supportive.")
    elif not close_above_ma20 and not close_above_ma50 and not macd_bullish:
        score -= 10
        trend_direction = "Bearish"
        reasons.append("Momentum trend is weak, which lowers swing-trade quality.")
    else:
        trend_direction = "Neutral"
        reasons.append("Momentum trend is mixed, so the swing setup needs better alignment.")

    aligned = close_above_ma50 and macd_bullish and daily_rsi < 70
    return (
        RegimeScore(
            label=REGIME_MOMENTUM,
            score=_clamp_score(int(round(score))),
            aligned=aligned,
            setup_type="Daily momentum swing",
            explanation="Daily trend, RSI, and volume support a live 5-15 day swing entry.",
            reasons=reasons,
        ),
        trend_direction,
    )


def _score_swing_mean_reversion(
    *,
    current_price: float,
    daily_rsi: float,
    ma20: float,
    ma50: float,
    ma200: float,
    volume_ratio: float,
    macd_bullish: bool,
) -> RegimeScore:
    score = 38
    reasons: list[str] = []
    above_ma200 = current_price > ma200
    ma50_above_ma200 = ma50 > ma200
    pullback_to_ma20 = current_price <= ma20 * 1.03
    pullback_to_ma50 = current_price <= ma50 * 1.05

    if above_ma200:
        score += 16
        reasons.append("Price remains above MA200, so the pullback is occurring inside a larger constructive trend.")
    else:
        score -= 12
        reasons.append("Price is below MA200, making mean-reversion buying less reliable.")

    if above_ma200 and ma50_above_ma200:
        score += 8
        reasons.append("MA50 is still above MA200, which supports a buy-the-dip framework.")

    if 35 <= daily_rsi <= 48:
        score += 16
        reasons.append("Daily RSI is reset enough for a swing bounce without showing complete trend failure.")
    elif 48 < daily_rsi <= 55:
        score += 6
        reasons.append("Daily RSI has cooled modestly, though it is not deeply reset.")
    else:
        score -= 8
        reasons.append("Daily RSI is not in a clean pullback range for mean reversion.")

    if pullback_to_ma20 or pullback_to_ma50:
        score += 12
        reasons.append("Price is pulling into MA20/MA50 support, giving the setup a logical location.")
    else:
        score -= 6
        reasons.append("Price is not close enough to moving-average support for a disciplined pullback entry.")

    if 0.8 <= volume_ratio <= 1.5:
        score += 5
        reasons.append("Volume is controlled, which helps the pullback look orderly.")
    elif volume_ratio > 2.0:
        score -= 5
        reasons.append("Volume is unusually heavy, so the pullback may reflect distribution rather than a reset.")

    if macd_bullish:
        score += 4
        reasons.append("MACD remains supportive enough for a bounce attempt.")

    aligned = above_ma200 and ma50_above_ma200 and daily_rsi <= 55 and (pullback_to_ma20 or pullback_to_ma50)
    return RegimeScore(
        label=REGIME_MEAN_REVERSION,
        score=_clamp_score(int(round(score))),
        aligned=aligned,
        setup_type="Mean-reversion swing pullback",
        explanation="The daily uptrend is intact while price and RSI pull back toward a logical support area.",
        reasons=reasons,
    )


def _build_swing_trade_view(history: pd.DataFrame) -> tuple[TradeSetupView, str, float, float]:
    latest = history.iloc[-1]
    recent = history.tail(20)

    current_price = _positive_float(latest["Close"], 0.01)
    daily_rsi = _safe_float(latest["RSI"], 50.0)
    ma20 = _positive_float(latest["MA20"], current_price)
    ma50 = _positive_float(latest["MA50"], current_price)
    recent_low = _positive_float(recent["Low"].min(), current_price)
    recent_high = _positive_float(recent["High"].max(), current_price)
    volume_average = _safe_float(recent["Volume"].mean(), 1.0)
    volume_ratio = _safe_float(latest["Volume"], volume_average) / max(volume_average, 1.0)
    macd_bullish = _safe_float(latest["MACD"]) > _safe_float(latest["MACD_SIGNAL"])
    close_above_ma20 = current_price > ma20
    close_above_ma50 = current_price > ma50
    ma200 = _positive_float(latest["MA200"], current_price)

    momentum, trend_direction = _score_swing_momentum(
        daily_rsi=daily_rsi,
        volume_ratio=volume_ratio,
        close_above_ma20=close_above_ma20,
        close_above_ma50=close_above_ma50,
        macd_bullish=macd_bullish,
    )
    mean_reversion = _score_swing_mean_reversion(
        current_price=current_price,
        daily_rsi=daily_rsi,
        ma20=ma20,
        ma50=ma50,
        ma200=ma200,
        volume_ratio=volume_ratio,
        macd_bullish=macd_bullish,
    )
    selected = _pick_regime(momentum, mean_reversion)

    if selected.label == REGIME_MOMENTUM and selected.score >= 74 and close_above_ma50 and current_price <= recent_high * 1.02 and daily_rsi < 70:
        state_label = "ENTER NOW"
        explanation = selected.explanation
    elif selected.label == REGIME_MEAN_REVERSION and selected.score >= 72 and selected.aligned:
        state_label = "ENTER NOW"
        explanation = selected.explanation
    elif selected.score >= 58 and (close_above_ma50 or selected.aligned):
        state_label = "WAIT FOR PULLBACK"
        explanation = "The swing setup is constructive, but a pullback toward support would offer better trade location."
    else:
        state_label = "NO TRADE"
        explanation = "The 5-15 day swing setup does not yet have enough alignment for the selected regime."

    pullback_entry = max(ma20, ma50)
    atr = _positive_float(latest.get("ATR14"), current_price * 0.02)
    risk_buffer = max(
        atr * (1.0 if selected.label == REGIME_MEAN_REVERSION else 1.5),
        current_price * 0.005,
    )
    entry_price = current_price if state_label == "ENTER NOW" else min(current_price, pullback_entry * 1.01)
    stop_loss = max(min(ma50 - risk_buffer, recent_low - risk_buffer * 0.5), 0.01)
    target_price = max(entry_price + 2 * max(entry_price - stop_loss, risk_buffer), entry_price + risk_buffer)

    return (
        _enforce_trade_setup_levels(TradeSetupView(
            horizon_label="5-15 Day Swing",
            score=selected.score,
            trade_state_label=state_label,
            trade_state_tone=_tone_for_state(state_label),
            holding_period_label="5-15 Days",
            setup_type=selected.setup_type,
            entry_price=round(entry_price, 2),
            target_price=round(target_price, 2),
            stop_loss_price=round(stop_loss, 2),
            explanation=explanation,
            reasons=selected.reasons,
            regime_label=selected.label,
            regime_scores={
                REGIME_MOMENTUM: momentum.score,
                REGIME_MEAN_REVERSION: mean_reversion.score,
            },
            ranking_bucket=f"5-15 Day Swing:{selected.label}",
            risk_unit=round(risk_buffer, 4),
        ), current_price),
        trend_direction,
        recent_high,
        recent_low,
    )


def build_short_term_view(
    history: pd.DataFrame,
    intraday_15m: pd.DataFrame | None = None,
    intraday_60m: pd.DataFrame | None = None,
) -> ShortTermView:
    day_trade = _build_day_trade_view(history, intraday_15m, intraday_60m)
    swing_trade, trend_direction, breakout_level, breakdown_level = _build_swing_trade_view(history)

    primary = day_trade if day_trade.score >= swing_trade.score else swing_trade
    reasons = primary.reasons + [f"The alternate short-term horizon currently scores {day_trade.score if primary is swing_trade else swing_trade.score}/100."]

    entry_idea = f"Entry near ${primary.entry_price:,.2f}."
    stop_loss_idea = f"Stop loss near ${primary.stop_loss_price:,.2f}."
    target_idea = f"Target near ${primary.target_price:,.2f}."
    invalidation_note = (
        "The setup loses validity if price fails to hold the planned entry zone and momentum stops confirming across the selected horizon."
    )

    return ShortTermView(
        score=primary.score,
        trend_direction=trend_direction,
        trade_state_label=primary.trade_state_label,
        trade_state_tone=primary.trade_state_tone,
        trade_state_explanation=primary.explanation,
        breakout_level=round(breakout_level, 2),
        breakdown_level=round(breakdown_level, 2),
        is_actionable_now=primary.trade_state_label == "ENTER NOW",
        setup_type=primary.setup_type,
        expected_holding_period=primary.holding_period_label,
        entry_idea=entry_idea,
        stop_loss_idea=stop_loss_idea,
        target_idea=target_idea,
        day_trade=day_trade,
        swing_trade=swing_trade,
        primary_horizon_label=primary.horizon_label,
        primary_regime_label=primary.regime_label,
        primary_ranking_bucket=primary.ranking_bucket,
        regime_scores={
            f"day_{REGIME_MOMENTUM.lower()}": day_trade.regime_scores.get(REGIME_MOMENTUM, 0),
            f"day_{REGIME_MEAN_REVERSION.lower()}": day_trade.regime_scores.get(REGIME_MEAN_REVERSION, 0),
            f"swing_{REGIME_MOMENTUM.lower()}": swing_trade.regime_scores.get(REGIME_MOMENTUM, 0),
            f"swing_{REGIME_MEAN_REVERSION.lower()}": swing_trade.regime_scores.get(REGIME_MEAN_REVERSION, 0),
        },
        reasons=reasons,
        invalidation_note=invalidation_note,
    )


def apply_earnings_lockout(view: ShortTermView, days_to_earnings: int | None) -> ShortTermView:
    """Withhold actionable entries inside the binary earnings-event window."""
    if days_to_earnings is None or not 0 <= days_to_earnings <= 3:
        return view

    guarded = deepcopy(view)
    lockout_state = "EARNINGS EVENT LOCKOUT"
    lockout_message = (
        f"New entries are withheld because earnings are due in {days_to_earnings} "
        f"trading day{'s' if days_to_earnings != 1 else ''}; normal stops cannot control gap risk."
    )
    for setup in (guarded.day_trade, guarded.swing_trade):
        if setup.trade_state_label == "ENTER NOW":
            setup.trade_state_label = lockout_state
            setup.trade_state_tone = "negative"
            setup.explanation = lockout_message

    if guarded.trade_state_label == "ENTER NOW":
        guarded.trade_state_label = lockout_state
        guarded.trade_state_tone = "negative"
        guarded.trade_state_explanation = lockout_message
    guarded.is_actionable_now = False
    guarded.invalidation_note = lockout_message
    guarded.reasons = [lockout_message, *guarded.reasons]
    return guarded


def apply_momentum_context_guard(
    view: ShortTermView,
    *,
    relative_strength_score: int | None,
    relative_strength_coverage: int,
    hostile_macro_regime: bool,
) -> ShortTermView:
    """Downgrade immediate momentum entries when independent risk context conflicts."""
    if view.primary_regime_label != REGIME_MOMENTUM or view.trade_state_label != "ENTER NOW":
        return view

    conflicts: list[str] = []
    if relative_strength_coverage >= 70 and relative_strength_score is not None and relative_strength_score < 43:
        conflicts.append("validated relative-strength context classifies the stock as an underperformer")
    if hostile_macro_regime:
        conflicts.append("credit spreads and financial conditions indicate a hostile macro regime")
    if not conflicts:
        return view

    guarded = deepcopy(view)
    message = "Immediate momentum entry is withheld because " + " and ".join(conflicts) + "."
    guarded.trade_state_label = "WAIT FOR CONTEXT CONFIRMATION"
    guarded.trade_state_tone = "watch"
    guarded.trade_state_explanation = message
    guarded.is_actionable_now = False
    primary_setup = guarded.day_trade if guarded.primary_horizon_label == guarded.day_trade.horizon_label else guarded.swing_trade
    primary_setup.trade_state_label = guarded.trade_state_label
    primary_setup.trade_state_tone = guarded.trade_state_tone
    primary_setup.explanation = message
    guarded.reasons = [message, *guarded.reasons]
    return guarded
