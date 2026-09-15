#!/usr/bin/env python3
"""Run the SC 13D activist shadow experiment without changing live ranking.

Usage:
  python scripts/run_sc13d_shadow.py --fixture
  python scripts/run_sc13d_shadow.py --corpus path/to/filings.json
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

from application.sc13d_shadow_service import Sc13dShadowService
from domain.research.sc13d_event_study import evaluate_sc13d_experiment, price_panel_from_frames
from providers.events.sc13d_models import Form4BuyEvent, Sc13dFiling


PURPOSE_ACTIVIST = (
    "Item 4. Purpose of Transaction. The Reporting Person acquired the shares to "
    "seek board representation and may nominate directors. The Reporting Person "
    "intends to discuss strategic alternatives and maximize shareholder value."
)
PURPOSE_PASSIVE = (
    "Item 4. Purpose of Transaction. The securities were acquired solely for "
    "investment. The Reporting Person has no present plans or proposals and is "
    "not acquired for the purpose of changing or influencing control of the issuer."
)


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


def _filing(**overrides: object) -> Sc13dFiling:
    payload = {
        "accession_number": "0001",
        "form": "SC 13D",
        "filed_at": "2016-03-01",
        "ticker": "AAA",
        "issuer_cik": "0000000001",
        "issuer_name": "AAA Inc",
        "reporting_cik": "0000000100",
        "reporting_name": "Star Fund",
        "url": "https://www.sec.gov/Archives/edgar/data/1/0001/doc.htm",
        "purpose_text": PURPOSE_ACTIVIST,
        "percent_of_class": 6.4,
        "source": "fixture",
    }
    payload.update(overrides)
    return Sc13dFiling(**payload)  # type: ignore[arg-type]


def fixture_experiment() -> dict:
    start = date(2015, 1, 2)
    spy = _history(start, 520, 100.0, 0.02)
    sector = _history(start, 520, 50.0, 0.01)
    stocks = {
        "AAA": _history(start, 520, 20.0, 0.08),
        "BBB": _history(start, 520, 20.0, 0.00),
        "CCC": _history(start, 520, 20.0, 0.07),
        "DDD": _history(start, 520, 20.0, 0.09),
    }
    filings: list[Sc13dFiling] = []
    form4: list[Form4BuyEvent] = []
    event_start = date(2016, 1, 4)
    for index in range(15):
        filed = event_start + timedelta(days=index * 21)
        filings.append(
            _filing(
                accession_number=f"AAA-{index}",
                ticker="AAA",
                reporting_cik="0000000101",
                filed_at=filed.isoformat(),
                percent_of_class=5.5 + index * 0.1,
            )
        )
        filings.append(
            _filing(
                accession_number=f"CCC-{index}",
                ticker="CCC",
                reporting_cik="0000000102",
                filed_at=filed.isoformat(),
                percent_of_class=7.0,
            )
        )
        filings.append(
            _filing(
                accession_number=f"DDD-{index}",
                ticker="DDD",
                reporting_cik="0000000105",
                filed_at=filed.isoformat(),
                percent_of_class=9.2,
            )
        )
        filings.append(
            _filing(
                accession_number=f"BBB-{index}",
                ticker="BBB",
                reporting_cik="0000000103",
                filed_at=filed.isoformat(),
                purpose_text=PURPOSE_PASSIVE,
                percent_of_class=8.0,
            )
        )
        if index % 5 == 0:
            form4.append(Form4BuyEvent("AAA", filed.isoformat(), f"F4-{index}"))
    filings.append(
        _filing(
            accession_number="AAA-convert",
            ticker="AAA",
            reporting_cik="0000000104",
            filed_at=(event_start + timedelta(days=40)).isoformat(),
            purpose_text=PURPOSE_ACTIVIST + " This statement converts this Schedule 13G into a Schedule 13D.",
            conversion_text_flag=True,
        )
    )
    panel = price_panel_from_frames(
        stocks,
        spy,
        sector_histories={"XLK": sector},
        ticker_sector={"AAA": "XLK", "BBB": "XLK", "CCC": "XLK", "DDD": "XLK"},
    )
    return evaluate_sc13d_experiment(filings, panel, form4_buys=form4)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SC 13D activist shadow event study (no live ranking changes)."
    )
    parser.add_argument("--corpus", type=Path, help="JSON or JSONL SC 13D corpus.")
    parser.add_argument("--fixture", action="store_true", help="Run the deterministic aligned fixture.")
    args = parser.parse_args()

    if args.corpus:
        ingest = Sc13dShadowService().ingest_corpus(args.corpus)
        print(json.dumps(ingest, indent=2))
        print("Corpus stored. Run with --fixture for a complete synthetic evaluation, or supply a price panel in-process.")
        return 0

    payload = fixture_experiment()
    payload.pop("event_rows", None)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
