from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from config.section16 import SECTION16_TRANSACTIONS_FILE
from providers.events.section16_models import InsiderTransaction
from storage.cache.json_cache import load_json, save_json


class Section16Repository:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or SECTION16_TRANSACTIONS_FILE

    def load_transactions(self) -> list[InsiderTransaction]:
        payload = load_json(self._path, {"transactions": []})
        rows = payload.get("transactions") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        transactions: list[InsiderTransaction] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                transactions.append(InsiderTransaction.from_dict(row))
            except (TypeError, ValueError):
                continue
        return transactions

    def save_transactions(self, transactions: Sequence[InsiderTransaction]) -> None:
        save_json(
            self._path,
            {
                "primary_source": "sec_insider_transactions_dataset",
                "mode": "shadow",
                "transactions": [row.to_dict() for row in transactions],
            },
        )

    def replace_with(self, transactions: Sequence[InsiderTransaction]) -> int:
        self.save_transactions(transactions)
        return len(transactions)

    def merge(self, incoming: Sequence[InsiderTransaction]) -> int:
        existing = {
            (row.accession_number, row.owner_cik, row.transaction_date, row.transaction_code, row.shares)
            for row in self.load_transactions()
        }
        merged = self.load_transactions()
        added = 0
        for row in incoming:
            key = (row.accession_number, row.owner_cik, row.transaction_date, row.transaction_code, row.shares)
            if key in existing:
                continue
            merged.append(row)
            existing.add(key)
            added += 1
        self.save_transactions(merged)
        return added
