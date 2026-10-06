from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from config.form144 import FORM144_LAST_RUN_FILE, PRIMARY_SOURCE, protocol_payload
from domain.research.form144_features import with_affiliate_flags
from domain.research.form144_match_study import PricePanel, evaluate_form144_experiment
from domain.scoring.form144_intent import (
    Form144IntentView,
    build_form144_intent_view,
    build_unavailable_form144_intent_view,
)
from providers.events.form144_dataset import parse_source
from providers.events.form144_models import Form4Sale, ProposedSaleNotice
from providers.events.form4_sale_store import discover_form4_keep_store, merge_form4_sales
from storage.cache.json_cache import save_json
from storage.repositories.form144_repository import Form144Repository


class Form144ShadowService:
    """Shadow-only Form 144 intent experiment. Never writes live score thresholds."""

    def __init__(
        self,
        repository: Form144Repository | None = None,
        *,
        last_run_path: Path | None = None,
    ) -> None:
        self._repository = repository or Form144Repository()
        self._last_run_path = last_run_path or FORM144_LAST_RUN_FILE

    def ingest_sec_source(self, source: Path, *, replace: bool = False) -> dict[str, Any]:
        notices = with_affiliate_flags(parse_source(source))
        stored = (
            self._repository.replace_with(notices)
            if replace
            else self._repository.merge(notices)
        )
        return {
            "mode": "shadow",
            "primary_source": PRIMARY_SOURCE,
            "ingested": len(notices),
            "stored": stored,
            "source": str(source),
            "live_ranking_changes": False,
        }

    def view_for_ticker(
        self,
        ticker: str,
        *,
        as_of: str | None = None,
        notices: Sequence[ProposedSaleNotice] | None = None,
        sales: Sequence[Form4Sale] | None = None,
    ) -> Form144IntentView:
        rows = list(notices) if notices is not None else self._repository.load_notices()
        if not any((row.ticker or "").upper() == ticker.upper().strip() for row in rows):
            return build_unavailable_form144_intent_view(
                "No mapped Form 144 notices are cached for this ticker."
            )
        return build_form144_intent_view(
            ticker=ticker,
            notices=rows,
            sales=sales,
            as_of=as_of,
        )

    def run_match_study(
        self,
        *,
        notices: Sequence[ProposedSaleNotice] | None = None,
        sales: Sequence[Form4Sale] | None = None,
        panel: PricePanel | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        rows = list(notices) if notices is not None else self._repository.load_notices()
        discovered = discover_form4_keep_store()
        form4_sales = merge_form4_sales(sales or (), discovered.get("sales") or ())
        payload = evaluate_form144_experiment(
            rows,
            form4_sales,
            panel=panel,
            form4_store_meta={
                key: value
                for key, value in discovered.items()
                if key != "sales"
            }
            | {"sale_count": len(form4_sales)},
        )
        payload["protocol"] = {
            **protocol_payload(),
            **payload.get("protocol", {}),
        }
        payload["generated_at"] = datetime.now(UTC).isoformat()
        if persist:
            save_json(
                self._last_run_path,
                {
                    key: value
                    for key, value in payload.items()
                    if key not in {"event_rows", "nested_rows"}
                },
            )
        return payload


__all__ = ["Form144ShadowService"]
