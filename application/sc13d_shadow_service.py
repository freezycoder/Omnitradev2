from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from config.sc13d import (
    SC13D_APPLIED_IMPACT,
    SC13D_LAST_RUN_FILE,
    SC13D_MODELED_IMPACT,
    protocol_payload,
)
from domain.research.sc13d_event_study import PricePanel, evaluate_sc13d_experiment
from providers.events.sc13d_edgar import Sc13dEdgarClient, load_corpus_file
from providers.events.sc13d_models import Form4BuyEvent, Sc13dFiling
from providers.events.sec_edgar_client import SecEventBundle
from storage.cache.json_cache import load_json, save_json
from storage.repositories.sc13d_repository import Sc13dRepository


class Sc13dShadowService:
    """Shadow-only SC 13D activist event study. Never writes live scores or recs."""

    def __init__(
        self,
        repository: Sc13dRepository | None = None,
        last_run_path: Path | None = None,
        edgar_client: Sc13dEdgarClient | None = None,
    ) -> None:
        self._repository = repository or Sc13dRepository()
        self._last_run_path = last_run_path or SC13D_LAST_RUN_FILE
        self._edgar_client = edgar_client

    def ingest_corpus(self, path: Path) -> dict[str, Any]:
        filings = load_corpus_file(path)
        thirteen_g = [row for row in filings if row.form.startswith("SC 13G")]
        thirteen_d = [row for row in filings if row.form.startswith("SC 13D")]
        stored = self._repository.replace_with(thirteen_d, thirteen_g=thirteen_g)
        return {
            "mode": "shadow",
            "live_ranking_changes": False,
            "path": str(path),
            "sc13d": stored,
            "sc13g": len(thirteen_g),
        }

    def ingest_tickers(self, tickers: Sequence[str], *, fetch_documents: bool = True) -> dict[str, Any]:
        client = self._edgar_client or Sc13dEdgarClient()
        payload = client.ingest_ticker_submissions(tickers, fetch_documents=fetch_documents)
        stored = self._repository.replace_with(payload["sc13d"], thirteen_g=payload["sc13g"])
        return {
            "mode": "shadow",
            "live_ranking_changes": False,
            "tickers": list(tickers),
            "sc13d": stored,
            "sc13g": len(payload["sc13g"]),
        }

    def run_event_study(
        self,
        panel: PricePanel,
        *,
        filings: Sequence[Sc13dFiling] | None = None,
        thirteen_g: Sequence[Sc13dFiling] | None = None,
        form4_buys: Sequence[Form4BuyEvent] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        rows = list(filings) if filings is not None else self._repository.load_filings()
        payload = evaluate_sc13d_experiment(
            rows,
            panel,
            thirteen_g=thirteen_g,
            form4_buys=form4_buys,
        )
        payload["generated_at"] = datetime.now(UTC).isoformat()
        shadow_rows = [
            {
                **{key: value for key, value in row.items() if key != "matched_phrases"},
                "matched_phrases": row.get("matched_phrases"),
                "logged_at": payload["generated_at"],
                "protocol_version": payload["protocol_version"],
            }
            for row in payload.get("event_rows", [])
        ]
        if persist:
            self._repository.append_shadow_log(shadow_rows)
            save_json(
                self._last_run_path,
                {key: value for key, value in payload.items() if key != "event_rows"},
            )
        return payload

    def calibration_payload(self) -> dict[str, Any]:
        stored = load_json(self._last_run_path, default=None)
        if not isinstance(stored, dict) or not stored:
            return {
                "mode": "shadow",
                "automatic_activation": False,
                "live_ranking_changes": False,
                "applied_impact": SC13D_APPLIED_IMPACT,
                "modeled_impact": SC13D_MODELED_IMPACT,
                "status": "not_run",
                "verdict": "INCONCLUSIVE",
                "verdict_status": "Not run",
                "summary": (
                    "The SC 13D activist shadow experiment has not been evaluated yet. "
                    "Run scripts/run_sc13d_shadow.py. Live recommendations are unchanged."
                ),
                "protocol": protocol_payload(),
                "diagnostic": {
                    "title": "SC 13D activist shadow experiment",
                    "status": "Not run",
                    "summary": "No last_experiment.json is cached.",
                    "expectation": "Shadow-only. Applied impact stays 0.",
                },
            }
        diagnostic_status = {
            "SUCCESS": "Aligned",
            "FAIL": "Not aligned",
            "INCONCLUSIVE": "Insufficient data",
        }.get(str(stored.get("verdict")), "Insufficient data")
        return {
            **stored,
            "mode": "shadow",
            "automatic_activation": False,
            "live_ranking_changes": False,
            "applied_impact": SC13D_APPLIED_IMPACT,
            "modeled_impact": SC13D_MODELED_IMPACT,
            "status": stored.get("verdict_status") or stored.get("status") or "shadow_research_only",
            "summary": stored.get("reason")
            or "SC 13D activist CAR remains shadow-only and does not change live recommendations.",
            "diagnostic": {
                "title": "SC 13D activist shadow experiment",
                "status": diagnostic_status,
                "summary": stored.get("reason") or "Shadow evaluation is cached.",
                "expectation": (
                    "Pre-registered activist 13Ds should show significant positive post-file "
                    "CAR in at least two walk-forward folds, after excluding passive language "
                    "and measuring the (−20,−1) run-up separately."
                ),
            },
        }


def form4_buys_from_bundles(bundles: Sequence[SecEventBundle]) -> list[Form4BuyEvent]:
    events: list[Form4BuyEvent] = []
    for bundle in bundles:
        for event in bundle.events:
            if event.category not in {"insider_purchase", "insider_purchase_cluster"}:
                continue
            if event.accession_number == "cluster":
                continue
            events.append(
                Form4BuyEvent(
                    ticker=bundle.ticker,
                    filed_at=event.filed_at,
                    accession_number=event.accession_number,
                    category=event.category,
                )
            )
    return events


__all__ = ["Sc13dShadowService", "form4_buys_from_bundles"]
