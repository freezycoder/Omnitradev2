#!/usr/bin/env python3
"""Build the shadow KCRORO panel and run the frozen nested-gate eval.

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

from application.kcroro_regime_eval_service import KcroroRegimeEvalService
from config.kcroro_regime import ICE_REDISTRIBUTION_NOTICE, KCRORO_CITATION
from providers.macro.kcroro_client import KcroroClient
from providers.market.market_provider import fetch_price_histories


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        default="2y",
        help="yfinance period for SPY (equity-vol control) and optional VIX.",
    )
    parser.add_argument(
        "--with-vix",
        action="store_true",
        help="Fetch ^VIX as an optional nested-model control (not a gate input).",
    )
    parser.add_argument(
        "--no-public-csv",
        action="store_true",
        help="Disable the public FRED CSV fallback (API/ALFRED only).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON path for the research-only payload.",
    )
    args = parser.parse_args()

    client = KcroroClient(allow_public_csv=not args.no_public_csv)
    bundle = client.fetch_bundle()
    tickers = ["SPY"]
    if args.with_vix:
        tickers.append("^VIX")
    spy_histories = {}
    try:
        spy_histories = fetch_price_histories(tickers, period=args.period)
    except Exception as exc:  # pragma: no cover - provider/network guard
        print(f"Price download failed ({exc!r}).", file=sys.stderr)
    spy_history = spy_histories.get("SPY", pd.DataFrame())
    vix_history = spy_histories.get("^VIX", pd.DataFrame()) if args.with_vix else pd.DataFrame()

    payload: dict[str, Any] = KcroroRegimeEvalService().evaluate_bundle(
        bundle,
        spy_history=None if spy_history.empty else spy_history,
        vix_history=None if vix_history.empty else vix_history,
    )
    payload["cli"] = {
        "citation": KCRORO_CITATION,
        "ice_redistribution_notice": ICE_REDISTRIBUTION_NOTICE,
        "spy_available": not spy_history.empty,
        "vix_available": not vix_history.empty,
        "series_status": bundle.status,
        "series_source": bundle.source,
    }
    text = json.dumps(payload, indent=2, default=str)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    outcome = str(payload.get("verdict", {}).get("outcome") or "aborted")
    return 0 if outcome in {"success", "fail", "aborted"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
