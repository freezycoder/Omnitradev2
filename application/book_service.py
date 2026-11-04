from __future__ import annotations

from typing import Any

from domain.portfolio.book_analysis import BookAnalysis, BookHolding, analyze_book
from storage.repositories.operator_book_repository import OperatorBookRepository
from storage.repositories.scan_repository import load_latest_view_scan, load_real_scan_cache


def load_cached_scan() -> dict[str, Any]:
    view = load_latest_view_scan()
    if isinstance(view, dict) and (view.get("long_term") or view.get("short_term")):
        return view
    cached = load_real_scan_cache()
    if isinstance(cached, dict):
        return cached
    return {}


def snapshot(book: OperatorBookRepository, scan: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = scan if scan is not None else load_cached_scan()
    holdings = book.load()
    analysis = analyze_book(
        holdings,
        _rows(payload, "long_term"),
        _rows(payload, "short_term"),
    )
    return _public_snapshot(book.store_name, payload, analysis)


def replace_holdings(
    book: OperatorBookRepository,
    holdings: tuple[BookHolding, ...],
    scan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    book.save(holdings)
    return snapshot(book, scan)


def _public_snapshot(store_name: str, scan: dict[str, Any], analysis: BookAnalysis) -> dict[str, Any]:
    return {
        "store": store_name,
        "scan_source": scan.get("source"),
        "scan_updated_at": scan.get("updated_at"),
        "summary": analysis.summary,
        "cash_pct": analysis.cash_pct,
        "largest_weight_pct": analysis.largest_weight_pct,
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
            }
            for position in analysis.positions
        ],
    }


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]
