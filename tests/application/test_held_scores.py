from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import application.held_scores as held_scores
from application.book_service import held_long_rows
from domain.portfolio.book_analysis import BookHolding, analyze_book


NOW = datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc)


def _fake_row(result):
    return {
        "ticker": result.ticker,
        "sector": "Consumer Defensive",
        "long_term_score": 72,
        "recommendation_label": "Buy",
    }


def test_only_unscanned_stocks_are_scored(monkeypatch) -> None:
    pending = held_scores.held_tickers_to_score(
        ["AAPL", "KO", "vwce", "imax", "KO"],
        [{"ticker": "AAPL"}],
    )
    assert pending == ["KO", "IMAX"]


def test_scores_are_cached_for_a_day(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(held_scores, "build_held_long_term_row", _fake_row)
    calls: list[str] = []

    def analyze(ticker: str):
        calls.append(ticker)
        return SimpleNamespace(ticker=ticker, data_source="live")

    path = tmp_path / "held.json"
    first = held_scores.score_held_tickers(["KO"], now=NOW, path=path, analyze=analyze)
    second = held_scores.score_held_tickers(["KO"], now=NOW + timedelta(hours=2), path=path, analyze=analyze)
    third = held_scores.score_held_tickers(["KO"], now=NOW + timedelta(hours=25), path=path, analyze=analyze)

    assert first[0]["scored_for_portfolio"] is True
    assert second == first
    assert len(third) == 1
    assert calls == ["KO", "KO"]


def test_demo_and_missing_data_are_not_scores(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(held_scores, "build_held_long_term_row", _fake_row)

    def analyze(ticker: str):
        if ticker == "DEMO":
            return SimpleNamespace(ticker=ticker, data_source="demo")
        return None

    rows = held_scores.score_held_tickers(["DEMO", "ZZZZ"], now=NOW, path=tmp_path / "held.json", analyze=analyze)
    assert rows == []


def test_held_rows_turn_not_in_scan_into_a_scored_position() -> None:
    holdings = (BookHolding("AAPL", 10), BookHolding("KO", 5))

    def held(tickers):
        return [
            {
                "ticker": ticker,
                "sector": "Consumer Defensive",
                "long_term_score": 72,
                "recommendation_label": "Buy",
                "scored_for_portfolio": True,
            }
            for ticker in tickers
        ]

    rows = held_long_rows(
        holdings,
        [{"ticker": "AAPL", "sector": "Technology", "long_term_score": 90, "recommendation_label": "Strong Buy"}],
        held,
    )
    analysis = analyze_book(holdings, rows)
    by_ticker = {position.ticker: position for position in analysis.positions}

    assert by_ticker["AAPL"].coverage == "scan"
    assert by_ticker["KO"].coverage == "portfolio"
    assert by_ticker["KO"].long_term_score == 72
    assert by_ticker["KO"].role == "neutral"
