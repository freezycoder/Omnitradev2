from __future__ import annotations

from pathlib import Path
from typing import Sequence

from config.form13f import FORM13F_HOLDINGS_FILE
from providers.events.form13f_models import HoldingPosition
from storage.cache.json_cache import load_json, save_json


class Form13FRepository:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or FORM13F_HOLDINGS_FILE

    def load_holdings(self) -> list[HoldingPosition]:
        payload = load_json(self._path, {"holdings": []})
        rows = payload.get("holdings") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        holdings: list[HoldingPosition] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                holdings.append(HoldingPosition.from_dict(row))
            except (TypeError, ValueError):
                continue
        return holdings

    def save_holdings(self, holdings: Sequence[HoldingPosition]) -> None:
        save_json(
            self._path,
            {
                "primary_source": "sec_form13f_data_sets",
                "mode": "shadow",
                "holdings": [row.to_dict() for row in holdings],
            },
        )

    def replace_with(self, holdings: Sequence[HoldingPosition]) -> int:
        self.save_holdings(holdings)
        return len(holdings)

    def merge(self, incoming: Sequence[HoldingPosition]) -> int:
        existing = {
            (row.accession_number, row.manager_cik, row.cusip, row.reportable_quarter)
            for row in self.load_holdings()
        }
        merged = self.load_holdings()
        for row in incoming:
            key = (row.accession_number, row.manager_cik, row.cusip, row.reportable_quarter)
            if key in existing:
                continue
            merged.append(row)
            existing.add(key)
        self.save_holdings(merged)
        return len(merged)
