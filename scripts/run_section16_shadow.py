#!/usr/bin/env python3
"""Run the Section-16 shadow experiment without changing live ranking.

Usage:
  python scripts/run_section16_shadow.py --fixture
  python scripts/run_section16_shadow.py --source path/to/quarterly_insider.zip
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.section16_shadow_service import Section16ShadowService, price_panel_from_frames
from domain.research.section16_event_study import evaluate_section16_experiment
from providers.events.sec_edgar_client import SecEventBundle, SecFilingEvent
from providers.events.section16_models import InsiderTransaction


def _history(start: date, sessions: int, start_price: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=sessions)
    closes = [start_price + index * step for index in range(sessions)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": [1_000_000] * sessions,
        },
        index=dates,
    )


def _transaction(**overrides: object) -> InsiderTransaction:
    payload = {
        "accession_number": "0001",
        "ticker": "AAA",
        "issuer_cik": "1",
        "issuer_name": "AAA Inc",
        "owner_cik": "100",
        "owner_name": "Buyer",
        "owner_title": "Director",
        "is_director": True,
        "is_officer": False,
        "is_ten_percent_owner": False,
        "transaction_date": "2024-01-02",
        "filed_at": "2024-01-02",
        "transaction_code": "P",
        "acquired_disposed": "A",
        "shares": 1000.0,
        "price_per_share": 20.0,
        "value_usd": 20_000.0,
        "is_10b5_1": False,
        "is_derivative": False,
        "source": "sec_quarterly_zip",
    }
    payload.update(overrides)
    return InsiderTransaction(**payload)  # type: ignore[arg-type]


def fixture_experiment() -> dict:
    start = date(2024, 1, 2)
    spy = _history(start, 160, 100.0, 0.05)
    sector = _history(start, 160, 50.0, 0.04)
    stocks = {
        "AAA": _history(start, 160, 20.0, 0.35),
        "BBB": _history(start, 160, 20.0, 0.02),
        "CCC": _history(start, 160, 20.0, 0.30),
    }
    transactions: list[InsiderTransaction] = []
    edgar_events: list[SecEventBundle] = []
    for index in range(12):
        filed = (start + timedelta(days=index * 10)).isoformat()
        for owner in ("101", "102", "103"):
            transactions.append(
                _transaction(
                    accession_number=f"AAA-{index}-{owner}",
                    ticker="AAA",
                    owner_cik=owner,
                    filed_at=filed,
                    transaction_date=filed,
                    value_usd=25_000.0,
                    shares=1000.0,
                )
            )
        edgar_events.append(
            SecEventBundle(
                ticker="AAA",
                cik="1",
                status="available",
                retrieved_at=filed,
                events=[
                    SecFilingEvent("4", filed, "insider_purchase", 1, 2, "purchase", "https://sec", f"AAA-{index}-101")
                ],
            )
        )
        transactions.append(
            _transaction(
                accession_number=f"BBB-{index}",
                ticker="BBB",
                owner_cik="201",
                filed_at=filed,
                transaction_date=filed,
                transaction_code="S",
                acquired_disposed="D",
                value_usd=15_000.0,
            )
        )
    panel = price_panel_from_frames(stocks, spy, sector_histories={"XLK": sector}, ticker_sector={"AAA": "XLK", "BBB": "XLK", "CCC": "XLK"})
    return evaluate_section16_experiment(transactions, panel, edgar_bundles=edgar_events, xml_path_available=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Section-16 shadow event study (no live ranking changes).")
    parser.add_argument("--source", type=Path, help="SEC quarterly ZIP or extracted TSV directory.")
    parser.add_argument("--fixture", action="store_true", help="Run the deterministic aligned fixture.")
    args = parser.parse_args()

    if args.source:
        ingest = Section16ShadowService().ingest_sec_source(args.source, replace=True)
        print(json.dumps(ingest, indent=2))
        print("Ingest stored. Run the event study with a price panel, or use --fixture for a complete synthetic evaluation.")
        return 0

    payload = fixture_experiment()
    payload.pop("event_rows", None)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
