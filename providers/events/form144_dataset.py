from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from providers.events.form144_models import ProposedSaleNotice
from providers.events.form144_xml import parse_form144_xml


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def parse_form144_file(
    path: Path,
    *,
    accession_number: str | None = None,
    filed_at: str | None = None,
    fallback_ticker: str | None = None,
    fallback_issuer_cik: str | None = None,
) -> ProposedSaleNotice:
    accession = accession_number or path.stem
    filed = filed_at or "1970-01-01"
    return parse_form144_xml(
        _read_bytes(path),
        accession_number=accession,
        filed_at=filed,
        fallback_ticker=fallback_ticker,
        fallback_issuer_cik=fallback_issuer_cik,
    )


def parse_source(source: Path) -> list[ProposedSaleNotice]:
    if source.is_file():
        if source.suffix.lower() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
            rows = payload.get("notices") if isinstance(payload, dict) else payload
            notices: list[ProposedSaleNotice] = []
            for row in rows or []:
                if isinstance(row, dict):
                    notices.append(ProposedSaleNotice.from_dict(row))
            return notices
        return [parse_form144_file(source)]
    notices: list[ProposedSaleNotice] = []
    for path in sorted(source.glob("**/*")):
        if path.suffix.lower() not in {".xml", ".txt"}:
            continue
        try:
            notices.append(parse_form144_file(path))
        except (ValueError, OSError):
            continue
    return notices


def notices_from_dicts(rows: Sequence[dict[str, Any]]) -> list[ProposedSaleNotice]:
    return [ProposedSaleNotice.from_dict(row) for row in rows]


__all__ = ["notices_from_dicts", "parse_form144_file", "parse_source"]
