from __future__ import annotations

from domain.signals.signal_buckets import (
    ACTIVE_BUCKET,
    EXCLUDED_BUCKET,
    WAITING_BUCKET,
    apply_short_term_signal_buckets,
    classify_short_term_signal,
)


def test_active_requires_explicit_actionability_and_actionable_state() -> None:
    row = {
        "trade_state": "ENTER NOW",
        "recommendation_label": "Strong Setup",
        "is_actionable_now": True,
    }

    assert classify_short_term_signal(row) == ACTIVE_BUCKET
    assert classify_short_term_signal({**row, "is_actionable_now": False}) == WAITING_BUCKET
    assert classify_short_term_signal({**row, "trade_state": "NO TRADE"}) == WAITING_BUCKET


def test_waiting_includes_monitored_setups() -> None:
    assert classify_short_term_signal(
        {
            "trade_state": "WAIT FOR PULLBACK",
            "recommendation_label": "Strong Setup",
            "is_actionable_now": False,
        }
    ) == WAITING_BUCKET
    assert classify_short_term_signal(
        {
            "trade_state": "NO TRADE",
            "recommendation_label": "Watchlist",
            "is_actionable_now": False,
        }
    ) == WAITING_BUCKET


def test_neutral_and_blocked_rows_are_excluded() -> None:
    assert classify_short_term_signal(
        {
            "trade_state": "NO TRADE",
            "recommendation_label": "Neutral",
            "is_actionable_now": False,
        }
    ) == EXCLUDED_BUCKET
    assert classify_short_term_signal(
        {
            "trade_state": "ENTER NOW",
            "recommendation_label": "Strong Setup",
            "is_actionable_now": True,
            "action_block_reason": "Scan data is stale.",
        }
    ) == EXCLUDED_BUCKET


def test_policy_attaches_buckets_and_exact_counts_without_mutating_input() -> None:
    payload = {
        "market_stats": {"short_candidates": 3},
        "short_term": [
            {
                "ticker": "AAPL",
                "trade_state": "ENTER NOW",
                "recommendation_label": "Strong Setup",
                "is_actionable_now": True,
            },
            {
                "ticker": "MSFT",
                "trade_state": "WAIT FOR PULLBACK",
                "recommendation_label": "Strong Setup",
                "is_actionable_now": False,
            },
            {
                "ticker": "NVDA",
                "trade_state": "NO TRADE",
                "recommendation_label": "Neutral",
                "is_actionable_now": False,
            },
        ],
    }

    protected = apply_short_term_signal_buckets(payload)

    assert [row["signal_bucket"] for row in protected["short_term"]] == [
        ACTIVE_BUCKET,
        WAITING_BUCKET,
        EXCLUDED_BUCKET,
    ]
    assert protected["market_stats"]["actionable_now"] == 1
    assert protected["market_stats"]["short_term_buckets"] == {
        "active": 1,
        "waiting": 1,
        "excluded": 1,
    }
    assert "signal_bucket" not in payload["short_term"][0]


def test_policy_recomputes_stale_bucket_metadata() -> None:
    payload = {
        "market_stats": {
            "actionable_now": 9,
            "short_term_buckets": {"active": 9, "waiting": 0, "excluded": 0},
        },
        "short_term": [
            {
                "ticker": "AAPL",
                "trade_state": "STALE — REFRESH REQUIRED",
                "recommendation_label": "STALE — REFRESH REQUIRED",
                "is_actionable_now": False,
                "action_block_reason": "Scan data is stale.",
                "signal_bucket": "active",
            }
        ],
    }

    protected = apply_short_term_signal_buckets(payload)

    assert protected["short_term"][0]["signal_bucket"] == EXCLUDED_BUCKET
    assert protected["market_stats"]["actionable_now"] == 0
    assert protected["market_stats"]["short_term_buckets"] == {
        "active": 0,
        "waiting": 0,
        "excluded": 1,
    }
