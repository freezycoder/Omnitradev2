from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class LongTermFactorWeights:
    trend_factor: float = 1.0
    quality_factor: float = 1.0
    growth_factor: float = 1.0
    valuation_factor: float = 1.0
    balance_sheet_factor: float = 1.0


@dataclass(frozen=True)
class FactorResult:
    key: str
    points: int
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


LONG_TERM_FACTOR_WEIGHTS = LongTermFactorWeights()


@dataclass
class LongTermView:
    score: int
    summary: str
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    thesis: str = ""
    news_score: int = 50
    news_impact: int = 0
    news_summary: str = ""
    news_signals: list[str] = field(default_factory=list)
    trend_factor: int = 50
    quality_factor: int = 50
    growth_factor: int = 50
    valuation_factor: int = 50
    balance_sheet_factor: int = 50
    factor_points: dict[str, int] = field(default_factory=dict)
    factor_weights: dict[str, float] = field(default_factory=dict)


def _clamp_score(score: int) -> int:
    return max(0, min(100, score))


def _compute_six_month_return(history: pd.DataFrame) -> float:
    if history.empty:
        return 0.0

    baseline = float(history.iloc[-126]["Close"]) if len(history) >= 126 else float(history.iloc[0]["Close"])
    current = float(history.iloc[-1]["Close"])
    if baseline == 0:
        return 0.0
    return (current / baseline) - 1


def _factor_score(points: int) -> int:
    return _clamp_score(50 + points)


def _score_trend_factor(latest: pd.Series, six_month_return: float) -> FactorResult:
    points = 0
    strengths: list[str] = []
    risks: list[str] = []

    if latest["Close"] > latest["MA200"]:
        points += 15
        strengths.append("Shares are trading above the 200-day average, which keeps the primary trend constructive.")
    else:
        points -= 8
        risks.append("Shares remain below the 200-day average, so the longer-term trend still needs repair.")

    if latest["MA50"] > latest["MA200"]:
        points += 10
        strengths.append("The 50-day average is above the 200-day average, signaling improving long-term momentum.")
    else:
        risks.append("The medium-term moving average has not yet reclaimed the long-term trend line.")

    if six_month_return > 0.12:
        points += 10
        strengths.append("The stock has delivered a healthy six-month return, showing sustained demand.")
    elif six_month_return < -0.1:
        points -= 10
        risks.append("The six-month price trend is still negative, which limits conviction for fresh long-term entries.")

    return FactorResult("trend_factor", points, strengths, risks)


def _score_growth_factor(fundamentals: dict) -> FactorResult:
    points = 0
    strengths: list[str] = []
    risks: list[str] = []

    revenue_growth = fundamentals.get("revenueGrowth")
    if revenue_growth is not None:
        if revenue_growth > 0.1:
            points += 10
            strengths.append("Revenue growth is healthy enough to support a multi-year expansion narrative.")
        elif revenue_growth < 0:
            points -= 10
            risks.append("Revenue growth is negative, which weakens the business momentum behind the chart.")

    earnings_growth = fundamentals.get("earningsGrowth")
    if earnings_growth is not None:
        if earnings_growth > 0.1:
            points += 8
            strengths.append("Earnings growth adds durability to the long-term case beyond simple revenue expansion.")
        elif earnings_growth < 0:
            points -= 6
            risks.append("Negative earnings growth suggests consistency still needs to improve.")

    return FactorResult("growth_factor", points, strengths, risks)


def _score_quality_factor(fundamentals: dict) -> FactorResult:
    points = 0
    strengths: list[str] = []
    risks: list[str] = []

    profit_margins = fundamentals.get("profitMargins")
    if profit_margins is not None:
        if profit_margins > 0.1:
            points += 10
            strengths.append("Profit margins are comfortably positive, which points to a resilient operating model.")
        elif profit_margins < 0:
            points -= 10
            risks.append("Profit margins are negative, so execution risk remains elevated.")

    return_on_equity = fundamentals.get("returnOnEquity")
    if return_on_equity is not None:
        if return_on_equity > 0.15:
            points += 8
            strengths.append("Return on equity suggests the business is converting capital into profits efficiently.")
        elif return_on_equity < 0.05:
            points -= 5
            risks.append("Return on equity is muted, which makes the quality profile less compelling.")

    return FactorResult("quality_factor", points, strengths, risks)


def _score_valuation_factor(fundamentals: dict) -> FactorResult:
    points = 0
    strengths: list[str] = []
    risks: list[str] = []

    trailing_pe = fundamentals.get("trailingPE")
    forward_pe = fundamentals.get("forwardPE")
    reference_pe = forward_pe if isinstance(forward_pe, (int, float)) and forward_pe > 0 else trailing_pe
    if reference_pe is not None:
        if 0 < reference_pe <= 25:
            points += 8
            strengths.append("Forward or trailing earnings valuation is within a reasonable range for a long-term holder.")
        elif reference_pe > 40:
            points -= 5
            risks.append("Valuation is elevated, so future returns may rely on continued strong execution.")

    market_cap = fundamentals.get("marketCap")
    free_cash_flow = fundamentals.get("freeCashflow")
    if (
        isinstance(market_cap, (int, float))
        and market_cap > 0
        and isinstance(free_cash_flow, (int, float))
    ):
        fcf_yield = free_cash_flow / market_cap
        if fcf_yield >= 0.05:
            points += 5
            strengths.append("Free-cash-flow yield provides tangible valuation support.")
        elif fcf_yield < 0:
            points -= 5
            risks.append("Negative free cash flow weakens support from headline earnings multiples.")

    enterprise_to_ebitda = fundamentals.get("enterpriseToEbitda")
    if isinstance(enterprise_to_ebitda, (int, float)) and enterprise_to_ebitda > 0:
        if enterprise_to_ebitda <= 12:
            points += 3
        elif enterprise_to_ebitda >= 25:
            points -= 3
            risks.append("Enterprise value is high relative to operating earnings.")

    return FactorResult("valuation_factor", points, strengths, risks)


def _score_balance_sheet_factor(fundamentals: dict) -> FactorResult:
    points = 0
    strengths: list[str] = []
    risks: list[str] = []

    debt_to_equity = fundamentals.get("debtToEquity")
    if debt_to_equity is not None:
        if debt_to_equity < 100:
            points += 5
            strengths.append("Balance-sheet leverage looks manageable for a longer holding period.")
        elif debt_to_equity > 200:
            points -= 5
            risks.append("Leverage is on the high side and could pressure downside resilience.")

    current_ratio = fundamentals.get("currentRatio")
    if current_ratio is not None:
        if current_ratio >= 1:
            points += 5
            strengths.append("Liquidity looks adequate, which helps reinforce balance-sheet durability.")
        elif current_ratio < 0.8:
            points -= 5
            risks.append("Short-term liquidity is tighter than ideal and can reduce financial flexibility.")

    return FactorResult("balance_sheet_factor", points, strengths, risks)


def _weighted_factor_points(factors: list[FactorResult], weights: LongTermFactorWeights) -> int:
    weighted = 0.0
    for factor in factors:
        weighted += factor.points * float(getattr(weights, factor.key))
    return int(round(weighted))


def build_long_term_view(history: pd.DataFrame, fundamentals: dict) -> LongTermView:
    latest = history.iloc[-1]
    six_month_return = _compute_six_month_return(history)
    factors = [
        _score_trend_factor(latest, six_month_return),
        _score_quality_factor(fundamentals),
        _score_growth_factor(fundamentals),
        _score_valuation_factor(fundamentals),
        _score_balance_sheet_factor(fundamentals),
    ]
    factor_points = {factor.key: factor.points for factor in factors}
    factor_scores = {factor.key: _factor_score(factor.points) for factor in factors}
    factor_weights = LONG_TERM_FACTOR_WEIGHTS
    score = 45 + _weighted_factor_points(factors, factor_weights)
    strengths = [message for factor in factors for message in factor.strengths]
    risks = [message for factor in factors for message in factor.risks]
    revenue_growth = fundamentals.get("revenueGrowth")
    profit_margins = fundamentals.get("profitMargins")

    if not strengths:
        strengths.append("The setup is mixed, so conviction mostly depends on future trend confirmation.")

    if not risks:
        risks.append("The main risk is that expectations remain high and the trend can still cool after a strong run.")

    trend_text = (
        "the stock is already in an established long-term uptrend"
        if latest["Close"] > latest["MA200"]
        else "the stock still needs stronger long-term trend confirmation"
    )
    growth_text = (
        "the business is still growing at a healthy clip"
        if isinstance(revenue_growth, (int, float)) and revenue_growth > 0.1
        else "future returns will depend more heavily on execution than rapid topline expansion"
    )
    quality_text = (
        "profitability gives management room to reinvest and defend margins"
        if isinstance(profit_margins, (int, float)) and profit_margins > 0.1
        else "profitability needs to remain stable to support the investment case"
    )
    thesis = (
        f"Over a three-to-five year horizon, the case is that {trend_text} while {growth_text}. "
        f"If management sustains execution, {quality_text}. "
        "The thesis weakens if trend support breaks down or if business quality metrics deteriorate."
    )

    summary = " ".join(strengths[:2] + risks[:1])
    return LongTermView(
        score=_clamp_score(int(round(score))),
        summary=summary,
        strengths=strengths,
        risks=risks,
        thesis=thesis,
        trend_factor=factor_scores["trend_factor"],
        quality_factor=factor_scores["quality_factor"],
        growth_factor=factor_scores["growth_factor"],
        valuation_factor=factor_scores["valuation_factor"],
        balance_sheet_factor=factor_scores["balance_sheet_factor"],
        factor_points=factor_points,
        factor_weights={
            "trend_factor": factor_weights.trend_factor,
            "quality_factor": factor_weights.quality_factor,
            "growth_factor": factor_weights.growth_factor,
            "valuation_factor": factor_weights.valuation_factor,
            "balance_sheet_factor": factor_weights.balance_sheet_factor,
        },
    )
