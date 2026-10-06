#!/usr/bin/env python3
"""Run the Form 144 intent shadow experiment without changing live ranking.

Usage:
  python scripts/run_form144_shadow.py --fixture
  python scripts/run_form144_shadow.py --fixture-mode same_day
  python scripts/run_form144_shadow.py --source path/to/form144.xml
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.form144_shadow_service import Form144ShadowService
from domain.research.form144_fixture import evaluate_aligned_fixture


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Form 144 proposed-sale shadow match study (no live ranking changes)."
    )
    parser.add_argument("--source", type=Path, help="Form 144 XML file, JSON, or directory.")
    parser.add_argument("--fixture", action="store_true", help="Run the deterministic CI fixture.")
    parser.add_argument(
        "--fixture-mode",
        choices=("lead", "same_day", "unmatched"),
        default="lead",
        help="Synthetic book: lead (calibration), same_day (infra), unmatched (fail).",
    )
    args = parser.parse_args()

    if args.source:
        ingest = Form144ShadowService().ingest_sec_source(args.source, replace=True)
        print(json.dumps(ingest, indent=2))
        print(
            "Ingest stored. Run --fixture for a complete synthetic evaluation, or supply "
            "Form 4 sales to application.form144_shadow_service.Form144ShadowService.run_match_study."
        )
        return 0

    payload = evaluate_aligned_fixture(mode=args.fixture_mode)
    payload.pop("event_rows", None)
    payload.pop("nested_rows", None)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
