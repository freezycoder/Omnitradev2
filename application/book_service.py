from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from application.held_scores import cached_held_rows, held_tickers_to_score, score_held_tickers
from domain.portfolio.book_analysis import BookAnalysis, BookHolding, analyze_book
from storage.repositories.operator_book_repository import OperatorBookRepository
from storage.repositories.scan_repository import load_latest_view_scan, load_real_scan_cache


HeldRowsFn = Callable[[Sequence[str]], list[dict[str, Any]]]


def load_cached_scan() -> dict[str, Any]:
    view = load_latest_view_scan()
    if isinstance(view, dict) and (view.get("long_term") or view.get("short_term")):
        return view
    cached = load_real_scan_cache()
    if isinstance(cached, dict):
        return cached
    return {}


def snapshot(
    book: OperatorBookRepository,
    scan: dict[str, Any] | None = None,
    *,
    held_rows: HeldRowsFn = cached_held_rows,
) -> dict[str, Any]:
    payload = scan if scan is not None else load_cached_scan()
    holdings = book.load()
    return _analyze(book.store_name, payload, holdings, held_rows)


def replace_holdings(
    book: OperatorBookRepository,
    holdings: tuple[BookHolding, ...],
    scan: dict[str, Any] | None = None,
    *,
    held_rows: HeldRowsFn = score_held_tickers,
) -> dict[str, Any]:
    book.save(holdings)
    payload = scan if scan is not None else load_cached_scan()
    return _analyze(book.store_name, payload, holdings, held_rows)


def rescore(
    book: OperatorBookRepository,
    scan: dict[str, Any] | None = None,
    *,
    held_rows: HeldRowsFn = score_held_tickers,
) -> dict[str, Any]:
    return snapshot(book, scan, held_rows=held_rows)


def held_long_rows(
    holdings: Sequence[BookHolding],
    long_rows: Sequence[dict[str, Any]],
    held_rows: HeldRowsFn = score_held_tickers,
) -> list[dict[str, Any]]:
    """Scanner rows plus a portfolio-only score for each held stock outside the scanner universe."""

    pending = held_tickers_to_score((holding.ticker for holding in holdings), long_rows)
    extra = held_rows(pending) if pending else []
    return [*long_rows, *extra]


def _analyze(
    store_name: str,
    payload: dict[str, Any],
    holdings: tuple[BookHolding, ...],
    held_rows: HeldRowsFn,
) -> dict[str, Any]:
    long_rows = held_long_rows(holdings, _rows(payload, "long_term"), held_rows)
    analysis = analyze_book(holdings, long_rows, _rows(payload, "short_term"))
    return _public_snapshot(store_name, payload, analysis)


def _public_snapshot(store_name: str, scan: dict[str, Any], analysis: BookAnalysis) -> dict[str, Any]:
    return {
        "store": store_name,
        "scan_source": scan.get("source"),
        "scan_updated_at": scan.get("updated_at"),
        "summary": analysis.summary,
        "cash_pct": analysis.cash_pct,
        "largest_weight_pct": analysis.largest_weight_pct,
        "posture": analysis.posture,
        "posture_label": analysis.posture_label,
        "posture_reason": analysis.posture_reason,
        "risk_score": analysis.risk_score,
        "strategies": [
            {
                "kind": item.kind,
                "ticker": item.ticker,
                "title": item.title,
                "detail": item.detail,
            }
            for item in analysis.strategies
        ],
        "risks": list(analysis.risks),
        "benefits": list(analysis.benefits),
        "holdings": [
            {"ticker": holding.ticker, "weight_pct": holding.weight_pct} for holding in analysis.holdings
        ],
        "positions": [
            {
                "ticker": position.ticker,
                "weight_pct": position.weight_pct,
                "sector": position.sector,
                "long_term_score": position.long_term_score,
                "recommendation_label": position.recommendation_label,
                "role": position.role,
                "shenanigan_risk": position.shenanigan_risk,
                "coverage": position.coverage,
            }
            for position in analysis.positions
        ],
    }


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]
