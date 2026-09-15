from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from config.form13f import FORM13F_LAST_RUN_FILE, PRIMARY_SOURCE, protocol_payload
from domain.research.form13f_event_study import PricePanel, evaluate_form13f_experiment
from domain.scoring.form13f_cluster import (
    Form13FClusterView,
    build_form13f_cluster_view,
    build_unavailable_form13f_cluster_view,
)
from providers.events.form13f_dataset import parse_source
from providers.events.form13f_models import HoldingPosition
from storage.cache.json_cache import save_json
from storage.repositories.form13f_repository import Form13FRepository


class Form13FShadowService:
    """Shadow-only 13F cluster experiment runner. Never writes live score thresholds."""

    def __init__(
        self,
        repository: Form13FRepository | None = None,
        *,
        last_run_path: Path | None = None,
    ) -> None:
        self._repository = repository or Form13FRepository()
        self._last_run_path = last_run_path or FORM13F_LAST_RUN_FILE

    def ingest_sec_source(self, source: Path, *, replace: bool = False) -> dict[str, Any]:
        holdings = parse_source(source)
        stored = (
            self._repository.replace_with(holdings)
            if replace
            else self._repository.merge(holdings)
        )
        return {
            "mode": "shadow",
            "primary_source": PRIMARY_SOURCE,
            "ingested": len(holdings),
            "stored": stored,
            "source": str(source),
            "live_ranking_changes": False,
        }

    def view_for_ticker(
        self,
        ticker: str,
        *,
        as_of: str | None = None,
        holdings: Sequence[HoldingPosition] | None = None,
    ) -> Form13FClusterView:
        rows = list(holdings) if holdings is not None else self._repository.load_holdings()
        if not any(row.ticker and row.ticker.upper() == ticker.upper().strip() for row in rows):
            return build_unavailable_form13f_cluster_view(
                "No mapped 13F holdings are cached for this ticker."
            )
        return build_form13f_cluster_view(ticker=ticker, holdings=rows, as_of=as_of)

    def run_event_study(
        self,
        panel: PricePanel,
        *,
        holdings: Sequence[HoldingPosition] | None = None,
        form4_cluster_keys: set[tuple[str, str]] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        rows = list(holdings) if holdings is not None else self._repository.load_holdings()
        payload = evaluate_form13f_experiment(
            rows,
            panel,
            form4_cluster_keys=form4_cluster_keys,
        )
        payload["protocol"] = {
            **protocol_payload(),
            **payload.get("protocol", {}),
        }
        payload["generated_at"] = datetime.now(UTC).isoformat()
        if persist:
            save_json(self._last_run_path, {key: value for key, value in payload.items() if key != "event_rows"})
        return payload


def price_panel_from_frames(
    stock_histories: dict[str, pd.DataFrame],
    spy_history: pd.DataFrame,
) -> PricePanel:
    def _close(frame: pd.DataFrame) -> pd.Series:
        close = pd.to_numeric(frame["Close"], errors="coerce")
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        return close.dropna().sort_index()

    def _volume(frame: pd.DataFrame) -> pd.Series:
        if "Volume" not in frame.columns:
            return pd.Series(dtype=float)
        volume = pd.to_numeric(frame["Volume"], errors="coerce")
        volume.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        return volume.dropna().sort_index()

    return PricePanel(
        stock={ticker.upper(): _close(frame) for ticker, frame in stock_histories.items()},
        spy=_close(spy_history),
        volume={ticker.upper(): _volume(frame) for ticker, frame in stock_histories.items()},
    )


__all__ = ["Form13FShadowService", "price_panel_from_frames"]
