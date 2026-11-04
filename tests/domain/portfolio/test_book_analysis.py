from __future__ import annotations

import pytest

from domain.portfolio.book_analysis import BookHolding, analyze_book, parse_holdings


def test_parse_rejects_duplicate_blank_and_out_of_range_weights() -> None:
    with pytest.raises(ValueError, match="listed twice"):
        parse_holdings(
            [
                {"ticker": "aapl", "weight_pct": 10},
                {"ticker": "AAPL", "weight_pct": 5},
            ]
        )
    with pytest.raises(ValueError, match="not a symbol"):
        parse_holdings([{"ticker": "bad ticker", "weight_pct": 10}])
    with pytest.raises(ValueError, match="at most 100"):
        parse_holdings([{"ticker": "MSFT", "weight_pct": 101}])


def test_book_flags_concentration_weak_names_and_strong_buy_overlap() -> None:
    holdings = (
        BookHolding("AAPL", 30),
        BookHolding("MSFT", 25),
        BookHolding("XOM", 10),
        BookHolding("ZZZZ", 5),
    )
    analysis = analyze_book(
        holdings,
        [
            {"ticker": "AAPL", "sector": "Technology", "long_term_score": 88, "recommendation_label": "Strong Buy"},
            {"ticker": "MSFT", "sector": "Technology", "long_term_score": 86, "recommendation_label": "Strong Buy"},
            {"ticker": "XOM", "sector": "Energy", "long_term_score": 40, "recommendation_label": "Avoid"},
        ],
    )

    assert analysis.cash_pct == 30
    assert any("AAPL is 30.0% of the book." in item for item in analysis.risks)
    assert any(item.startswith("Technology is 55.0%") for item in analysis.risks)
    assert any("XOM" in item and "Avoid" in item for item in analysis.risks)
    assert any("ZZZZ" in item and "not in the latest scan" in item for item in analysis.risks)
    assert any("AAPL" in item and "Strong Buy" in item for item in analysis.benefits)
    assert any("MSFT" in item and "Strong Buy" in item for item in analysis.benefits)
    assert any(item.startswith("30.0% is unallocated") for item in analysis.benefits)
    assert analysis.mail_lines()[0] == "Your book"


def test_weights_above_100_are_called_out_and_do_not_invent_cash() -> None:
    analysis = analyze_book(
        (BookHolding("AAPL", 70), BookHolding("MSFT", 50)),
        [{"ticker": "AAPL", "sector": "Technology", "long_term_score": 70, "recommendation_label": "Buy"}],
    )
    assert analysis.cash_pct == 0
    assert any("above 100%" in item for item in analysis.risks)


def test_empty_book_has_no_mail_section() -> None:
    assert analyze_book((), []).mail_lines() == ()
