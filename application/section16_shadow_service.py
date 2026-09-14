from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from config.section16 import (
    FRESHNESS_SLA_DAYS,
    OVERLAP_ENRICHMENT_THRESHOLD_PCT,
    PRIMARY_SOURCE,
    SECTION16_LAST_RUN_FILE,
    TRACEFOUR_ENABLED_DEFAULT,
    protocol_payload,
)
from domain.research.section16_event_study import PricePanel, evaluate_section16_experiment
from domain.scoring.section16_insider import (
    Section16InsiderView,
    build_section16_insider_view,
    build_unavailable_section16_insider_view,
)
from providers.events.form4_xml import parse_form4_xml
from providers.events.sec_edgar_client import SecEventBundle
from providers.events.sec_insider_dataset import parse_source
from providers.events.section16_models import InsiderTransaction
from providers.events.tracefour_client import TracefourTerms, build_tracefour_client
from storage.cache.json_cache import save_json
from storage.repositories.section16_repository import Section16Repository


class Section16ShadowService:
    """Shadow-only Section-16 experiment runner. Never writes live score thresholds."""

    def __init__(
        self,
        repository: Section16Repository | None = None,
        *,
        last_run_path: Path | None = None,
    ) -> None:
        self._repository = repository or Section16Repository()
        self._last_run_path = last_run_path or SECTION16_LAST_RUN_FILE

    def ingest_sec_source(self, source: Path, *, replace: bool = False) -> dict[str, Any]:
        transactions = parse_source(source)
        stored = (
            self._repository.replace_with(transactions)
            if replace
            else self._repository.merge(transactions)
        )
        return {
            "mode": "shadow",
            "primary_source": PRIMARY_SOURCE,
            "ingested": len(transactions),
            "stored": stored,
            "source": str(source),
        }

    def ingest_form4_xml(
        self,
        payload: bytes | str,
        *,
        accession_number: str,
        filed_at: str,
        ticker: str | None = None,
        issuer_cik: str | None = None,
    ) -> int:
        rows = parse_form4_xml(
            payload,
            accession_number=accession_number,
            filed_at=filed_at,
            fallback_ticker=ticker,
            fallback_issuer_cik=issuer_cik,
        )
        return self._repository.merge(rows)

    def optional_tracefour_cross_check(self, *, enabled: bool = TRACEFOUR_ENABLED_DEFAULT) -> dict[str, Any]:
        client = build_tracefour_client(enabled=enabled)
        terms = client.terms
        if not enabled:
            return {
                "used": False,
                "role": terms.role,
                "never_primary": terms.never_primary,
                "terms": asdict(terms),
                "message": "Tracefour stayed disabled. SEC remains the primary Section-16 path.",
            }
        clusters = client.get_clusters()
        streaks = client.get_streaks()
        return {
            "used": True,
            "role": terms.role,
            "never_primary": terms.never_primary,
            "terms": asdict(terms),
            "cluster_count": len(clusters.get("data") or []) if isinstance(clusters.get("data"), list) else 0,
            "streak_count": len(streaks.get("data") or []) if isinstance(streaks.get("data"), list) else 0,
            "cluster_error": clusters.get("error"),
            "streak_error": streaks.get("error"),
        }

    def view_for_ticker(
        self,
        ticker: str,
        *,
        as_of: str | None = None,
        live_transactions: Sequence[InsiderTransaction] | None = None,
        sec_bundle: SecEventBundle | None = None,
    ) -> Section16InsiderView:
        stored = self._repository.load_transactions()
        combined = list(stored)
        if live_transactions:
            combined.extend(live_transactions)
        edgar_accessions = []
        if sec_bundle is not None:
            edgar_accessions = [
                event.accession_number
                for event in sec_bundle.events
                if event.form in {"4", "4/A"} and event.accession_number
            ]
            for row in getattr(sec_bundle, "open_market_transactions", []) or []:
                if isinstance(row, dict):
                    try:
                        combined.append(InsiderTransaction.from_dict(row))
                    except (TypeError, ValueError):
                        continue
        if not any(row.ticker.upper() == ticker.upper().strip() for row in combined):
            return build_unavailable_section16_insider_view(
                "No open-market Section-16 rows are cached for this ticker."
            )
        sources = {row.source for row in combined if row.ticker.upper() == ticker.upper().strip()}
        freshness_source = "mixed" if len(sources) > 1 else next(iter(sources), "unavailable")
        return build_section16_insider_view(
            ticker=ticker,
            transactions=combined,
            as_of=as_of,
            edgar_form4_accessions=edgar_accessions,
            freshness_source=freshness_source,
        )

    def run_event_study(
        self,
        panel: PricePanel,
        *,
        transactions: Sequence[InsiderTransaction] | None = None,
        edgar_bundles: Sequence[SecEventBundle] | None = None,
        xml_path_available: bool = True,
        persist: bool = True,
    ) -> dict[str, Any]:
        rows = list(transactions) if transactions is not None else self._repository.load_transactions()
        payload = evaluate_section16_experiment(
            rows,
            panel,
            edgar_bundles=edgar_bundles,
            xml_path_available=xml_path_available,
        )
        payload["protocol"] = {
            **protocol_payload(),
            **payload.get("protocol", {}),
            "freshness_sla_days": FRESHNESS_SLA_DAYS,
            "overlap_enrichment_threshold_pct": OVERLAP_ENRICHMENT_THRESHOLD_PCT,
        }
        payload["tracefour"] = self.optional_tracefour_cross_check(enabled=False)
        payload["generated_at"] = datetime.now(UTC).isoformat()
        if persist:
            save_json(self._last_run_path, {key: value for key, value in payload.items() if key != "event_rows"})
        return payload


def price_panel_from_frames(
    stock_histories: dict[str, pd.DataFrame],
    spy_history: pd.DataFrame,
    *,
    sector_histories: dict[str, pd.DataFrame] | None = None,
    ticker_sector: dict[str, str] | None = None,
) -> PricePanel:
    def _close(frame: pd.DataFrame) -> pd.Series:
        close = pd.to_numeric(frame["Close"], errors="coerce")
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        return close.dropna().sort_index()

    return PricePanel(
        stock={ticker.upper(): _close(frame) for ticker, frame in stock_histories.items()},
        spy=_close(spy_history),
        sector={symbol.upper(): _close(frame) for symbol, frame in (sector_histories or {}).items()},
        ticker_sector={ticker.upper(): sector.upper() for ticker, sector in (ticker_sector or {}).items()},
    )


__all__ = ["Section16ShadowService", "price_panel_from_frames"]
