"""Read-only Kronos forecast orchestration.

Pulls OHLCV from the existing market provider, asks the Kronos sidecar for a
forward path, and caches the answer per (ticker, horizon, last bar). Nothing
here writes to the signal store or feeds scoring, recommendations, or the
Performance Lab.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config.settings import DATA_DIR
from providers.forecast.kronos_client import KronosUnavailable, kronos_enabled, predict
from storage.cache.json_cache import load_json, save_json


log = logging.getLogger(__name__)

FORECAST_CACHE_DIR = DATA_DIR / "kronos_forecast"
DEFAULT_LOOKBACK = 400
MAX_LOOKBACK = 512
DEFAULT_HORIZON = 30
MAX_HORIZON = 120


def _cache_path(ticker: str, horizon: int) -> Path:
    return FORECAST_CACHE_DIR / f"{ticker.upper().strip()}_{horizon}.json"


def _future_trading_days(last_date: Any, horizon: int) -> list[str]:
    import pandas as pd

    start = pd.Timestamp(last_date) + pd.Timedelta(days=1)
    days = pd.bdate_range(start=start, periods=horizon)
    return [day.strftime("%Y-%m-%dT00:00:00") for day in days]


def _candles_from_history(history: Any, lookback: int) -> list[dict[str, Any]]:
    import pandas as pd

    frame = history.tail(lookback)
    candles: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        timestamp = pd.Timestamp(index)
        candles.append(
            {
                "t": timestamp.strftime("%Y-%m-%dT%H:%M:%S"),
                "o": float(row["Open"]),
                "h": float(row["High"]),
                "l": float(row["Low"]),
                "c": float(row["Close"]),
                "v": float(row.get("Volume", 0) or 0),
            }
        )
    return candles


def _trade_level_diagnostics(
    payload: dict[str, Any],
    *,
    entry_price: float | None,
    stop_loss_price: float | None,
    target_price: float | None,
) -> dict[str, Any] | None:
    if not all(value is not None and value > 0 for value in (entry_price, stop_loss_price, target_price)):
        return None
    bands = payload.get("bands")
    if not isinstance(bands, dict):
        return {
            "status": "unavailable",
            "summary": "Forecast quantile bands are unavailable, so trade levels cannot be validated.",
        }
    p10 = [float(value) for value in bands.get("p10", [])]
    p50 = [float(value) for value in bands.get("p50", [])]
    p90 = [float(value) for value in bands.get("p90", [])]
    if not p10 or not p50 or not p90:
        return {
            "status": "unavailable",
            "summary": "Forecast quantile bands are incomplete, so trade levels cannot be validated.",
        }

    stop_breach = min(p10) <= float(stop_loss_price)
    target_plausible = max(p90) >= float(target_price)
    median_return_pct = ((p50[-1] / float(entry_price)) - 1.0) * 100.0
    status = "conflict" if stop_breach or not target_plausible else "aligned"
    return {
        "status": status,
        "stop_breach_in_p10": stop_breach,
        "target_reached_by_p90": target_plausible,
        "median_horizon_return_pct": round(median_return_pct, 2),
        "entry_price": entry_price,
        "stop_loss_price": stop_loss_price,
        "target_price": target_price,
        "summary": (
            "Forecast uncertainty conflicts with at least one proposed trade level."
            if status == "conflict"
            else "Forecast quantiles are consistent with the proposed stop and target."
        ),
    }


def build_forecast(
    ticker: str,
    *,
    horizon: int = DEFAULT_HORIZON,
    lookback: int = DEFAULT_LOOKBACK,
    refresh: bool = False,
    entry_price: float | None = None,
    stop_loss_price: float | None = None,
    target_price: float | None = None,
) -> dict[str, Any]:
    """Return a Kronos forecast payload for `ticker`.

    Raises KronosUnavailable when the sidecar is disabled, unreachable, or the
    market provider has no usable history.
    """

    from providers.market.market_provider import fetch_price_history

    if not kronos_enabled():
        raise KronosUnavailable("Kronos forecasting is disabled for this deployment.")

    normalized_ticker = ticker.upper().strip()
    horizon = max(1, min(int(horizon), MAX_HORIZON))
    lookback = max(64, min(int(lookback), MAX_LOOKBACK))

    history = fetch_price_history(normalized_ticker)
    if history is None or getattr(history, "empty", True):
        raise KronosUnavailable(f"No price history is available for {normalized_ticker}.")

    last_bar = history.index[-1]
    last_bar_key = str(last_bar)[:10]
    cache_path = _cache_path(normalized_ticker, horizon)

    if not refresh:
        cached = load_json(cache_path, None)
        if isinstance(cached, dict) and cached.get("last_bar") == last_bar_key:
            cached_payload = {**cached, "cached": True}
            cached_payload["trade_level_diagnostics"] = _trade_level_diagnostics(
                cached_payload,
                entry_price=entry_price,
                stop_loss_price=stop_loss_price,
                target_price=target_price,
            )
            return cached_payload

    candles = _candles_from_history(history, lookback)
    future_timestamps = _future_trading_days(last_bar, horizon)
    forecast = predict(candles=candles, future_timestamps=future_timestamps)

    last_close = float(history["Close"].iloc[-1])
    final_close = float(forecast.points[-1].get("c", last_close))
    expected_return_pct = ((final_close / last_close) - 1.0) * 100.0 if last_close else None

    payload: dict[str, Any] = {
        "ticker": normalized_ticker,
        "model": forecast.model,
        "generated_at": forecast.generated_at or datetime.now(UTC).isoformat(),
        "last_bar": last_bar_key,
        "last_close": last_close,
        "horizon": horizon,
        "lookback": len(candles),
        "points": forecast.points,
        "bands": forecast.bands,
        "expected_close": final_close,
        "expected_return_pct": expected_return_pct,
        "trade_level_diagnostics": None,
        "disclaimer": (
            "Kronos output is a research forecast. It does not feed scoring, "
            "recommendations, or the Performance Lab."
        ),
        "cached": False,
    }
    payload["trade_level_diagnostics"] = _trade_level_diagnostics(
        payload,
        entry_price=entry_price,
        stop_loss_price=stop_loss_price,
        target_price=target_price,
    )

    try:
        save_json(cache_path, {**payload, "trade_level_diagnostics": None})
    except Exception:  # a read-only filesystem must not break the response
        log.warning("Could not cache Kronos forecast for %s.", normalized_ticker, exc_info=True)

    return payload


__all__ = ["build_forecast", "DEFAULT_HORIZON", "FORECAST_CACHE_DIR"]
