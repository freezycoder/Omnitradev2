"""Long-term scores for held tickers that the fixed scanner universe does not cover."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from application.scan_service import build_held_long_term_row
from application.ticker_service import TickerAnalysis, build_ticker_analysis
from config.settings import DATA_MODE_AUTO, HELD_SCORES_FILE
from domain.portfolio.known_etfs import resolve_known_etf
from storage.cache.json_cache import load_json, save_json


log = logging.getLogger(__name__)

HELD_SCORE_MAX_AGE = timedelta(hours=24)
# Each ticker costs a price history plus several Finnhub calls on the free tier.
MAX_HELD_TICKERS_PER_RUN = 15
_WORKERS = 4

Analyzer = Callable[[str], TickerAnalysis | None]


def _default_analyzer(ticker: str) -> TickerAnalysis | None:
    return build_ticker_analysis(ticker, data_mode=DATA_MODE_AUTO)


def held_tickers_to_score(tickers: Iterable[str], scanned_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    scanned = {str(row.get("ticker") or "").upper() for row in scanned_rows}
    pending: list[str] = []
    for ticker in tickers:
        normalized = ticker.upper().strip()
        if not normalized or normalized in scanned or resolve_known_etf(normalized) is not None:
            continue
        if normalized not in pending:
            pending.append(normalized)
    return pending


def cached_held_rows(
    tickers: Iterable[str],
    *,
    now: datetime | None = None,
    path: Path = HELD_SCORES_FILE,
) -> list[dict[str, Any]]:
    moment = now or datetime.now(timezone.utc)
    store = _load(path)
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        entry = store.get(ticker.upper())
        if entry is not None and _is_fresh(entry, moment):
            rows.append(dict(entry["row"]))
    return rows


def score_held_tickers(
    tickers: Iterable[str],
    *,
    now: datetime | None = None,
    path: Path = HELD_SCORES_FILE,
    analyze: Analyzer = _default_analyzer,
) -> list[dict[str, Any]]:
    """Return long-term rows for each ticker, refreshing entries older than a day."""

    moment = now or datetime.now(timezone.utc)
    store = _load(path)
    wanted = [ticker.upper().strip() for ticker in tickers if ticker.strip()]
    stale = [ticker for ticker in wanted if not _is_fresh(store.get(ticker), moment)]
    to_fetch = stale[:MAX_HELD_TICKERS_PER_RUN]
    if to_fetch:
        with ThreadPoolExecutor(max_workers=_WORKERS) as executor:
            results = list(executor.map(lambda ticker: (ticker, _safe_row(ticker, analyze)), to_fetch))
        changed = False
        for ticker, row in results:
            if row is None:
                continue
            store[ticker] = {"scored_at": moment.isoformat(), "row": row}
            changed = True
        if changed:
            save_json(path, store)
    rows: list[dict[str, Any]] = []
    for ticker in wanted:
        entry = store.get(ticker)
        if entry is not None:
            rows.append(dict(entry["row"]))
    return rows


def _safe_row(ticker: str, analyze: Analyzer) -> dict[str, Any] | None:
    try:
        result = analyze(ticker)
    except Exception:
        log.exception("held ticker %s could not be scored", ticker)
        return None
    if result is None or result.data_source == "demo":
        return None
    row = build_held_long_term_row(result)
    row["scored_for_portfolio"] = True
    return row


def _is_fresh(entry: Mapping[str, Any] | None, now: datetime) -> bool:
    if not entry or not isinstance(entry.get("row"), dict):
        return False
    try:
        scored_at = datetime.fromisoformat(str(entry["scored_at"]))
    except (KeyError, ValueError):
        return False
    if scored_at.tzinfo is None:
        scored_at = scored_at.replace(tzinfo=timezone.utc)
    age = now - scored_at
    return timedelta(0) <= age < HELD_SCORE_MAX_AGE


def _load(path: Path) -> dict[str, Any]:
    payload = load_json(path, {})
    return payload if isinstance(payload, dict) else {}
