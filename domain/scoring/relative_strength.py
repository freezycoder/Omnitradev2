from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class RelativeStrengthPeriod:
    key: str
    label: str
    sessions: int
    weight: float
    stock_return_pct: float | None
    market_return_pct: float | None
    market_excess_pct: float | None
    sector_return_pct: float | None
    sector_excess_pct: float | None
    sector_leadership_pct: float | None


@dataclass(frozen=True)
class RelativeStrengthView:
    mode: str
    status: str
    score: int | None
    applied_impact: int
    coverage_score: int
    sector: str
    market_benchmark_symbol: str
    sector_benchmark_symbol: str | None
    market_relative_pct: float | None
    sector_relative_pct: float | None
    sector_leadership_pct: float | None
    raw_strength_pct: float | None
    universe_percentile: int | None
    sector_percentile: int | None
    summary: str
    periods: list[RelativeStrengthPeriod] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    as_of_date: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_PERIOD_SPECS = (
    ("1m", "1 month", 21, 0.15),
    ("3m", "3 months", 63, 0.25),
    ("6m", "6 months", 126, 0.35),
    ("12m", "12 months", 252, 0.25),
)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _as_close_series(history: pd.DataFrame, *, as_of: pd.Timestamp | None = None) -> pd.Series:
    if history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().sort_index()
    if close.empty or as_of is None:
        return close
    try:
        return close.loc[close.index <= as_of]
    except TypeError:
        normalized = close.copy()
        normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
        normalized_as_of = as_of.tz_localize(None) if as_of.tzinfo else as_of
        return normalized.loc[normalized.index <= normalized_as_of]


def _period_return_pct(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    current = float(close.iloc[-1])
    baseline = float(close.iloc[-(sessions + 1)])
    if baseline <= 0:
        return None
    return (current / baseline - 1.0) * 100.0


def _weighted_average(values: list[tuple[float | None, float]]) -> float | None:
    available = [(float(value), weight) for value, weight in values if value is not None]
    total_weight = sum(weight for _, weight in available)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in available) / total_weight


def _status_for(score: int | None, coverage_score: int) -> str:
    if score is None or coverage_score < 40:
        return "unavailable"
    if score >= 70:
        return "leader"
    if score >= 58:
        return "outperforming"
    if score <= 30:
        return "lagging"
    if score <= 42:
        return "underperforming"
    return "neutral"


def build_relative_strength_view(
    *,
    stock_history: pd.DataFrame,
    market_history: pd.DataFrame,
    sector_history: pd.DataFrame,
    sector: str,
    market_symbol: str = "SPY",
    sector_symbol: str | None = None,
    warning: str | None = None,
) -> RelativeStrengthView:
    stock_close = _as_close_series(stock_history)
    if stock_close.empty:
        return build_unavailable_relative_strength_view(
            sector=sector,
            market_symbol=market_symbol,
            sector_symbol=sector_symbol,
            message="Stock price history is unavailable for relative-strength analysis.",
        )

    as_of = pd.Timestamp(stock_close.index[-1])
    market_close = _as_close_series(market_history, as_of=as_of)
    sector_close = _as_close_series(sector_history, as_of=as_of)
    periods: list[RelativeStrengthPeriod] = []
    market_weight_coverage = 0.0
    sector_weight_coverage = 0.0

    for key, label, sessions, weight in _PERIOD_SPECS:
        stock_return = _period_return_pct(stock_close, sessions)
        market_return = _period_return_pct(market_close, sessions)
        sector_return = _period_return_pct(sector_close, sessions)
        market_excess = (
            stock_return - market_return
            if stock_return is not None and market_return is not None
            else None
        )
        sector_excess = (
            stock_return - sector_return
            if stock_return is not None and sector_return is not None
            else None
        )
        sector_leadership = (
            sector_return - market_return
            if sector_return is not None and market_return is not None
            else None
        )
        if market_excess is not None:
            market_weight_coverage += weight
        if sector_excess is not None and sector_leadership is not None:
            sector_weight_coverage += weight
        periods.append(
            RelativeStrengthPeriod(
                key=key,
                label=label,
                sessions=sessions,
                weight=weight,
                stock_return_pct=round(stock_return, 2) if stock_return is not None else None,
                market_return_pct=round(market_return, 2) if market_return is not None else None,
                market_excess_pct=round(market_excess, 2) if market_excess is not None else None,
                sector_return_pct=round(sector_return, 2) if sector_return is not None else None,
                sector_excess_pct=round(sector_excess, 2) if sector_excess is not None else None,
                sector_leadership_pct=round(sector_leadership, 2) if sector_leadership is not None else None,
            )
        )

    market_relative = _weighted_average(
        [(period.market_excess_pct, period.weight) for period in periods]
    )
    sector_relative = _weighted_average(
        [(period.sector_excess_pct, period.weight) for period in periods]
    )
    sector_leadership = _weighted_average(
        [(period.sector_leadership_pct, period.weight) for period in periods]
    )
    raw_strength = _weighted_average(
        [
            (market_relative, 0.55),
            (sector_relative, 0.30),
            (sector_leadership, 0.15),
        ]
    )
    coverage_score = int(round(market_weight_coverage * 60 + sector_weight_coverage * 40))
    score = (
        int(round(_clamp(50 + float(raw_strength) * 1.75, 0, 100)))
        if raw_strength is not None
        else None
    )
    status = _status_for(score, coverage_score)
    evidence: list[str] = []
    for period in periods:
        if period.market_excess_pct is None:
            continue
        statement = (
            f"{period.label}: {period.market_excess_pct:+.1f} pp versus {market_symbol}"
        )
        if period.sector_excess_pct is not None and sector_symbol:
            statement += f" and {period.sector_excess_pct:+.1f} pp versus {sector_symbol}"
        evidence.append(f"{statement}.")

    warnings: list[str] = []
    if warning:
        warnings.append(warning)
    if sector_symbol is None:
        warnings.append("No sector ETF mapping was available; coverage is limited to the market benchmark.")
    elif sector_close.empty:
        warnings.append(f"{sector_symbol} history was unavailable; sector-relative comparisons are missing.")
    if market_close.empty:
        warnings.append(f"{market_symbol} history was unavailable; relative-strength scoring is disabled.")

    if status == "leader":
        summary = "The stock is a sustained leader versus both the market and its sector benchmark."
    elif status == "outperforming":
        summary = "The stock is outperforming its market and sector references on the weighted lookback."
    elif status == "lagging":
        summary = "The stock is a pronounced relative laggard across the weighted lookback."
    elif status == "underperforming":
        summary = "The stock is underperforming its market or sector references."
    elif status == "neutral":
        summary = "Relative performance is mixed and does not show decisive leadership."
    else:
        summary = "Relative-strength coverage is insufficient for interpretation."

    return RelativeStrengthView(
        mode="shadow",
        status=status,
        score=score,
        applied_impact=0,
        coverage_score=coverage_score,
        sector=sector or "N/A",
        market_benchmark_symbol=market_symbol,
        sector_benchmark_symbol=sector_symbol,
        market_relative_pct=round(market_relative, 2) if market_relative is not None else None,
        sector_relative_pct=round(sector_relative, 2) if sector_relative is not None else None,
        sector_leadership_pct=round(sector_leadership, 2) if sector_leadership is not None else None,
        raw_strength_pct=round(raw_strength, 2) if raw_strength is not None else None,
        universe_percentile=None,
        sector_percentile=None,
        summary=summary,
        periods=periods,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
        as_of_date=as_of.date().isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_relative_strength_view(
    *,
    sector: str,
    market_symbol: str = "SPY",
    sector_symbol: str | None = None,
    message: str,
) -> RelativeStrengthView:
    return RelativeStrengthView(
        mode="shadow",
        status="unavailable",
        score=None,
        applied_impact=0,
        coverage_score=0,
        sector=sector or "N/A",
        market_benchmark_symbol=market_symbol,
        sector_benchmark_symbol=sector_symbol,
        market_relative_pct=None,
        sector_relative_pct=None,
        sector_leadership_pct=None,
        raw_strength_pct=None,
        universe_percentile=None,
        sector_percentile=None,
        summary=message,
        warnings=[message],
        updated_at=datetime.now(UTC).isoformat(),
    )


def relative_strength_view_from_dict(payload: dict[str, Any] | None) -> RelativeStrengthView:
    if not isinstance(payload, dict):
        return build_unavailable_relative_strength_view(
            sector="N/A",
            message="The cached snapshot predates relative-strength analysis.",
        )
    period_rows = payload.get("periods")
    periods = [
        RelativeStrengthPeriod(**row)
        for row in period_rows or []
        if isinstance(row, dict)
    ]
    values = dict(payload)
    values["periods"] = periods
    return RelativeStrengthView(**values)


__all__ = [
    "RelativeStrengthPeriod",
    "RelativeStrengthView",
    "build_relative_strength_view",
    "build_unavailable_relative_strength_view",
    "relative_strength_view_from_dict",
]
