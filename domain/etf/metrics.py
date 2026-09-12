from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from config.etf import (
    MIN_BARS_FOR_1Y,
    MIN_BARS_FOR_3Y,
    MIN_BARS_FOR_5Y,
    MIN_BARS_FOR_DOWNSIDE,
    MIN_BARS_FOR_SHARPE,
    MIN_BARS_FOR_VOLATILITY,
)


TRADING_DAYS = {
    "1d": 1,
    "1w": 5,
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "1y": 252,
    "3y": 756,
    "5y": 1260,
}


@dataclass(frozen=True)
class EtfPerformanceMetrics:
    return_1d: float | None = None
    return_1w: float | None = None
    return_1m: float | None = None
    return_3m: float | None = None
    return_6m: float | None = None
    return_ytd: float | None = None
    return_1y: float | None = None
    return_3y: float | None = None
    return_5y: float | None = None
    current_price: float | None = None
    daily_change_pct: float | None = None
    annualized_volatility: float | None = None
    maximum_drawdown: float | None = None
    sharpe_ratio: float | None = None
    downside_volatility: float | None = None
    insufficient_data: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _close_series(history: pd.DataFrame) -> pd.Series:
    if history is None or history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if getattr(close.index, "tz", None) is not None:
        close = close.copy()
        close.index = close.index.tz_localize(None)
    return close.sort_index()


def period_return(close: pd.Series, trading_days: int) -> float | None:
    if close.size < trading_days + 1:
        return None
    start = float(close.iloc[-(trading_days + 1)])
    end = float(close.iloc[-1])
    if start == 0:
        return None
    return ((end / start) - 1.0) * 100.0


def ytd_return(close: pd.Series) -> float | None:
    if close.size < 2:
        return None
    year = close.index[-1].year
    year_slice = close[close.index.year == year]
    if year_slice.size < 2:
        prior = close[close.index.year < year]
        if prior.empty:
            return None
        start = float(prior.iloc[-1])
    else:
        start = float(year_slice.iloc[0])
    end = float(close.iloc[-1])
    if start == 0:
        return None
    return ((end / start) - 1.0) * 100.0


def annualized_volatility(close: pd.Series) -> float | None:
    if close.size < MIN_BARS_FOR_VOLATILITY:
        return None
    daily = close.pct_change().dropna()
    if daily.size < MIN_BARS_FOR_VOLATILITY - 1:
        return None
    return float(daily.std(ddof=0) * np.sqrt(252.0) * 100.0)


def maximum_drawdown(close: pd.Series) -> float | None:
    if close.size < MIN_BARS_FOR_VOLATILITY:
        return None
    running_max = close.cummax()
    drawdown = (close / running_max.replace(0, np.nan)) - 1.0
    worst = float(drawdown.min())
    if np.isnan(worst):
        return None
    return worst * 100.0


def sharpe_ratio(close: pd.Series) -> float | None:
    if close.size < MIN_BARS_FOR_SHARPE:
        return None
    daily = close.pct_change().dropna()
    if daily.size < MIN_BARS_FOR_SHARPE - 1:
        return None
    std = float(daily.std(ddof=0))
    if std == 0:
        return None
    return float((daily.mean() / std) * np.sqrt(252.0))


def downside_volatility(close: pd.Series) -> float | None:
    if close.size < MIN_BARS_FOR_DOWNSIDE:
        return None
    daily = close.pct_change().dropna()
    negative = daily[daily < 0]
    if negative.size < 10:
        return None
    return float(negative.std(ddof=0) * np.sqrt(252.0) * 100.0)


def aligned_correlation(left: pd.Series, right: pd.Series) -> float | None:
    combined = pd.concat([left.rename("a"), right.rename("b")], axis=1).dropna()
    if combined.shape[0] < MIN_BARS_FOR_VOLATILITY:
        return None
    value = combined["a"].pct_change().corr(combined["b"].pct_change())
    if value is None or np.isnan(value):
        return None
    return float(value)


def build_performance_metrics(history: pd.DataFrame) -> EtfPerformanceMetrics:
    close = _close_series(history)
    insufficient: list[str] = []
    if close.size < 2:
        return EtfPerformanceMetrics(insufficient_data=("price_history",))

    current_price = float(close.iloc[-1])
    daily_change = period_return(close, 1)
    metrics = {
        "return_1d": daily_change,
        "return_1w": period_return(close, TRADING_DAYS["1w"]),
        "return_1m": period_return(close, TRADING_DAYS["1m"]),
        "return_3m": period_return(close, TRADING_DAYS["3m"]),
        "return_6m": period_return(close, TRADING_DAYS["6m"]),
        "return_ytd": ytd_return(close),
        "return_1y": period_return(close, TRADING_DAYS["1y"]) if close.size >= MIN_BARS_FOR_1Y else None,
        "return_3y": period_return(close, TRADING_DAYS["3y"]) if close.size >= MIN_BARS_FOR_3Y else None,
        "return_5y": period_return(close, TRADING_DAYS["5y"]) if close.size >= MIN_BARS_FOR_5Y else None,
        "annualized_volatility": annualized_volatility(close),
        "maximum_drawdown": maximum_drawdown(close),
        "sharpe_ratio": sharpe_ratio(close),
        "downside_volatility": downside_volatility(close),
    }
    labels = {
        "return_1d": "1D",
        "return_1w": "1W",
        "return_1m": "1M",
        "return_3m": "3M",
        "return_6m": "6M",
        "return_ytd": "YTD",
        "return_1y": "1Y",
        "return_3y": "3Y",
        "return_5y": "5Y",
        "annualized_volatility": "volatility",
        "maximum_drawdown": "drawdown",
        "sharpe_ratio": "sharpe",
        "downside_volatility": "downside_volatility",
    }
    for key, label in labels.items():
        if metrics[key] is None:
            insufficient.append(label)
    return EtfPerformanceMetrics(
        current_price=current_price,
        daily_change_pct=daily_change,
        insufficient_data=tuple(insufficient),
        **metrics,
    )


__all__ = [
    "EtfPerformanceMetrics",
    "aligned_correlation",
    "build_performance_metrics",
    "period_return",
]
