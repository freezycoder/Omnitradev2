#!/usr/bin/env python3
"""Run the Form 13F cluster shadow experiment without changing live ranking.

Usage:
  python scripts/run_form13f_shadow.py --fixture
  python scripts/run_form13f_shadow.py --source path/to/13f.zip
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from application.form13f_shadow_service import Form13FShadowService
from domain.research.form13f_fixture import evaluate_aligned_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Form 13F cluster shadow event study (no live ranking changes).")
    parser.add_argument("--source", type=Path, help="SEC 13F ZIP or extracted TSV directory.")
    parser.add_argument("--fixture", action="store_true", help="Run the deterministic lag-correct fixture.")
    args = parser.parse_args()

    if args.source:
        ingest = Form13FShadowService().ingest_sec_source(args.source, replace=True)
        print(json.dumps(ingest, indent=2))
        print(
            "Ingest stored. Run the event study with a price panel, or use --fixture "
            "for a complete synthetic evaluation."
        )
        return 0

    payload = evaluate_aligned_fixture(with_burst=True)
    payload.pop("event_rows", None)
    print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
