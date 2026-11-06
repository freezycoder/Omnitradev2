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
    assert any("AAPL is 30.0% of the book, above the 20% single-name cap." in item for item in analysis.risks)
    assert any(item.startswith("Technology is 55.0%") for item in analysis.risks)
    assert any("XOM" in item and "Avoid" in item for item in analysis.risks)
    assert any("ZZZZ" in item and "no live price data" in item for item in analysis.risks)
    assert any("AAPL" in item and "Strong Buy" in item for item in analysis.benefits)
    assert any("MSFT" in item and "Strong Buy" in item for item in analysis.benefits)
    assert any(item.startswith("30.0% is unallocated") for item in analysis.benefits)
    assert analysis.posture == "trim"
    assert any(item.kind == "trim" and item.ticker == "AAPL" for item in analysis.strategies)
    assert any(item.kind == "review" and item.ticker == "XOM" for item in analysis.strategies)
    assert analysis.mail_lines()[0] == "Your portfolio"


def test_a_weak_concentrated_book_is_not_the_core() -> None:
    analysis = analyze_book(
        (BookHolding("XOM", 45), BookHolding("ZZZZ", 35)),
        [{"ticker": "XOM", "sector": "Energy", "long_term_score": 40, "recommendation_label": "Avoid"}],
    )
    assert analysis.posture == "rebuild"
    assert analysis.risk_score >= 55


def test_a_spread_out_strong_book_is_a_maintain_posture() -> None:
    analysis = analyze_book(
        (BookHolding("AAPL", 15), BookHolding("MSFT", 15), BookHolding("JPM", 10)),
        [
            {"ticker": "AAPL", "sector": "Technology", "long_term_score": 88, "recommendation_label": "Strong Buy"},
            {"ticker": "MSFT", "sector": "Technology", "long_term_score": 86, "recommendation_label": "Strong Buy"},
            {"ticker": "JPM", "sector": "Financials", "long_term_score": 84, "recommendation_label": "Strong Buy"},
            {"ticker": "NVDA", "sector": "Technology", "long_term_score": 91, "recommendation_label": "Strong Buy"},
        ],
    )

    assert analysis.posture == "maintain"
    assert analysis.risk_score < 25
    assert any(item.kind == "keep" and item.ticker == "AAPL" for item in analysis.strategies)
    assert any(item.kind == "research" and item.ticker == "NVDA" for item in analysis.strategies)


def test_weights_above_100_are_called_out_and_do_not_invent_cash() -> None:
    analysis = analyze_book(
        (BookHolding("AAPL", 70), BookHolding("MSFT", 50)),
        [{"ticker": "AAPL", "sector": "Technology", "long_term_score": 70, "recommendation_label": "Buy"}],
    )
    assert analysis.cash_pct == 0
    assert any("above 100%" in item for item in analysis.risks)


def test_ucits_aliases_collapse_and_are_not_missing_stocks() -> None:
    holdings = parse_holdings(
        [
            {"ticker": "vwra", "weight_pct": 50},
            {"ticker": "500", "weight_pct": 30},
            {"ticker": "qutm", "weight_pct": 10},
        ]
    )
    assert [item.ticker for item in holdings] == ["VWCE", "AUM5", "QNTM"]

    analysis = analyze_book(holdings, [])

    assert all("no live price data" not in item for item in analysis.risks)
    assert all(position.coverage == "fund" for position in analysis.positions)
    assert any("US large-cap equity" in item for item in analysis.risks)
    assert any(item.kind == "keep" and item.ticker == "VWCE" for item in analysis.strategies)
    assert any(item.kind == "review" and item.ticker == "AUM5" for item in analysis.strategies)
    assert any(item.kind == "keep" and item.ticker == "QNTM" for item in analysis.strategies)
    assert analysis.posture == "trim"


def test_a_large_quantum_fund_is_trimmed_as_a_satellite() -> None:
    analysis = analyze_book((BookHolding("QNTM", 25),), [])
    assert any(item.kind == "trim" and item.ticker == "QNTM" for item in analysis.strategies)
    assert any("satellite" in item for item in analysis.risks)


def test_horizons_blend_scores_and_buys_avoid_a_full_sector() -> None:
    analysis = analyze_book(
        (BookHolding("NVDA", 40),),
        [
            {
                "ticker": "NVDA",
                "sector": "Technology",
                "long_term_score": 90,
                "recommendation_label": "Strong Buy",
                "market_excess_6m_pct": 8,
            },
            {"ticker": "AVGO", "sector": "Technology", "long_term_score": 92, "recommendation_label": "Strong Buy"},
            {"ticker": "LLY", "sector": "Health Care", "long_term_score": 88, "recommendation_label": "Strong Buy"},
            {"ticker": "COST", "sector": "Health Care", "long_term_score": 91, "recommendation_label": "Strong Buy", "alternative_signal_applied_impact": 4},
        ],
        [{"ticker": "NVDA", "short_term_score": 70}],
    )

    by_key = {item.key: item for item in analysis.horizons}
    assert by_key["days"].value == 70
    assert by_key["months"].value == 8
    assert by_key["years"].value == 90
    assert [item.ticker for item in analysis.buys] == ["LLY"]
    assert "Health Care is 0% of this book." in analysis.buys[0].reason


def test_empty_book_has_no_mail_section() -> None:
    assert analyze_book((), []).mail_lines() == ()
