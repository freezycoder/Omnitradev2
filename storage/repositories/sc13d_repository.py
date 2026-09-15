from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from config.sc13d import SC13D_FILINGS_FILE, SC13D_SHADOW_LOG_FILE
from providers.events.sc13d_models import Sc13dFiling
from storage.cache.json_cache import load_json, save_json


class Sc13dRepository:
    def __init__(
        self,
        filings_path: Path | None = None,
        shadow_log_path: Path | None = None,
    ) -> None:
        self._filings_path = filings_path or SC13D_FILINGS_FILE
        self._shadow_log_path = shadow_log_path or SC13D_SHADOW_LOG_FILE

    def load_filings(self) -> list[Sc13dFiling]:
        payload = load_json(self._filings_path, {"filings": []})
        rows = payload.get("filings") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        filings: list[Sc13dFiling] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                filings.append(Sc13dFiling.from_dict(row))
            except (TypeError, ValueError):
                continue
        return filings

    def save_filings(self, filings: Sequence[Sc13dFiling], *, thirteen_g: Sequence[Sc13dFiling] | None = None) -> None:
        save_json(
            self._filings_path,
            {
                "mode": "shadow",
                "live_ranking_changes": False,
                "filings": [row.to_dict() for row in filings],
                "sc13g": [row.to_dict() for row in (thirteen_g or ())],
            },
        )

    def replace_with(
        self,
        filings: Sequence[Sc13dFiling],
        *,
        thirteen_g: Sequence[Sc13dFiling] | None = None,
    ) -> int:
        self.save_filings(filings, thirteen_g=thirteen_g)
        return len(filings)

    def append_shadow_log(self, rows: Sequence[dict]) -> None:
        if not rows:
            return
        self._shadow_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._shadow_log_path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")
