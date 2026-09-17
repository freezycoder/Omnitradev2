#!/usr/bin/env python3
"""Build the shadow market-breadth panel and run the frozen-gate eval.

This script never writes live scores, ranking, or recommendations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from application.market_breadth_eval_service import MarketBreadthEvalService
from config.market_breadth import RSP_SYMBOL, SPY_SYMBOL
from config.settings import DEMO_DATA_FILE
from config.universe import DEFAULT_STOCK_UNIVERSE
from providers.market.market_provider import fetch_price_histories, load_demo_stock_data


def _demo_histories(tickers: list[str]) -> dict[str, pd.DataFrame]:
    histories: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        loaded = load_demo_stock_data(ticker)
        if loaded is None:
            continue
        history, _fundamentals = loaded
        if history is not None and not history.empty:
            histories[ticker] = history
    return histories


def _load_histories(tickers: list[str], *, period: str, allow_demo: bool) -> dict[str, pd.DataFrame]:
    try:
        live = fetch_price_histories(tickers, period=period)
    except Exception as exc:  # pragma: no cover - provider/network guard
        print(f"Live price download failed ({exc!r}).", file=sys.stderr)
        live = {}
    usable = {ticker: frame for ticker, frame in live.items() if frame is not None and not frame.empty}
    if usable:
        return usable
    if not allow_demo:
        return {}
    print(
        f"Live histories were empty; falling back to demo data at {DEMO_DATA_FILE}.",
        file=sys.stderr,
    )
    return _demo_histories([ticker for ticker in tickers if ticker not in {SPY_SYMBOL, RSP_SYMBOL}])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        default="2y",
        help="yfinance period for the universe, SPY, and RSP (default: 2y).",
    )
    parser.add_argument(
        "--allow-demo-fallback",
        action="store_true",
        help="Use local demo OHLCV if live download fails. Demo history is too short for 200 DMA.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON path for the research-only payload.",
    )
    args = parser.parse_args()

    universe = list(DEFAULT_STOCK_UNIVERSE)
    requested = list(dict.fromkeys([*universe, SPY_SYMBOL, RSP_SYMBOL]))
    histories = _load_histories(
        requested,
        period=args.period,
        allow_demo=args.allow_demo_fallback,
    )
    spy_history = histories.pop(SPY_SYMBOL, pd.DataFrame())
    rsp_history = histories.pop(RSP_SYMBOL, pd.DataFrame())
    stock_histories = {ticker: histories[ticker] for ticker in universe if ticker in histories}

    payload: dict[str, Any] = MarketBreadthEvalService().evaluate_price_panel(
        stock_histories=stock_histories,
        spy_history=spy_history,
        rsp_history=None if rsp_history.empty else rsp_history,
        universe=universe,
    )
    text = json.dumps(payload, indent=2, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    outcome = str(payload.get("verdict", {}).get("outcome") or "aborted")
    return 0 if outcome in {"success", "fail", "aborted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
