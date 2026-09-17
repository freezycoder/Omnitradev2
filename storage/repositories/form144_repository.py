from __future__ import annotations

from pathlib import Path
from typing import Sequence

from config.form144 import FORM144_NOTICES_FILE, PRIMARY_SOURCE
from providers.events.form144_models import ProposedSaleNotice
from storage.cache.json_cache import load_json, save_json


class Form144Repository:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or FORM144_NOTICES_FILE

    def load_notices(self) -> list[ProposedSaleNotice]:
        payload = load_json(self._path, {"notices": []})
        rows = payload.get("notices") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        notices: list[ProposedSaleNotice] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                notices.append(ProposedSaleNotice.from_dict(row))
            except (TypeError, ValueError):
                continue
        return notices

    def save_notices(self, notices: Sequence[ProposedSaleNotice]) -> None:
        save_json(
            self._path,
            {
                "primary_source": PRIMARY_SOURCE,
                "mode": "shadow",
                "notices": [row.to_dict() for row in notices],
            },
        )

    def replace_with(self, notices: Sequence[ProposedSaleNotice]) -> int:
        self.save_notices(notices)
        return len(notices)

    def merge(self, incoming: Sequence[ProposedSaleNotice]) -> int:
        existing = {row.accession_number for row in self.load_notices()}
        merged = self.load_notices()
        for row in incoming:
            if row.accession_number in existing:
                continue
            merged.append(row)
            existing.add(row.accession_number)
        self.save_notices(merged)
        return len(merged)
