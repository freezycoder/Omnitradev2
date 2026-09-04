from __future__ import annotations

from datetime import UTC, datetime, timedelta

from domain.signals.freshness import apply_scan_freshness_policy


NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def _payload(*, source: str = "live", updated_at: str | None = None) -> dict:
    return {
        "source": source,
        "updated_at": updated_at,
        "market_stats": {"short_candidates": 1},
        "long_term": [{"ticker": "AAPL", "recommendation_label": "BUY"}],
        "short_term": [
            {
                "ticker": "AAPL",
                "trade_state": "ENTER NOW",
                "recommendation_label": "BUY",
                "is_actionable_now": True,
                "entry": "Enter near $100",
                "entry_price": 100.0,
                "target_price": 110.0,
                "stop_loss_price": 95.0,
                "breakout_level": 101.0,
                "day_trade": {
                    "trade_state": "ENTER NOW",
                    "entry_price": 100.0,
                    "target_price": 102.0,
                    "stop_loss_price": 99.0,
                },
            }
        ],
        "market_rows": [{"ticker": "AAPL", "trade_state": "ENTER NOW"}],
    }


def test_fresh_real_scan_keeps_actionable_signal() -> None:
    payload = _payload(updated_at=(NOW - timedelta(hours=2)).isoformat())

    protected = apply_scan_freshness_policy(payload, now=NOW)

    assert protected["data_status"]["status"] == "fresh"
    assert protected["data_status"]["is_actionable"] is True
    assert protected["market_stats"]["actionable_now"] == 1
    assert protected["market_stats"]["short_term_buckets"] == {
        "active": 1,
        "waiting": 0,
        "excluded": 0,
    }
    assert protected["short_term"][0]["trade_state"] == "ENTER NOW"
    assert protected["short_term"][0]["signal_bucket"] == "active"
    assert protected["short_term"][0]["entry_price"] == 100.0


def test_stale_cached_scan_blocks_states_and_all_price_levels() -> None:
    payload = _payload(updated_at=(NOW - timedelta(hours=25)).isoformat())

    protected = apply_scan_freshness_policy(payload, source_override="cached_real", now=NOW)

    signal = protected["short_term"][0]
    assert protected["source"] == "cached_real"
    assert protected["data_status"]["status"] == "stale"
    assert protected["data_status"]["is_actionable"] is False
    assert protected["data_status"]["blocked_actionable_count"] == 1
    assert protected["market_stats"]["actionable_now"] == 0
    assert protected["market_stats"]["short_term_buckets"] == {
        "active": 0,
        "waiting": 0,
        "excluded": 1,
    }
    assert signal["trade_state"] == "STALE — REFRESH REQUIRED"
    assert signal["signal_bucket"] == "excluded"
    assert "original_trade_state" not in signal
    assert "original_recommendation_label" not in signal
    assert signal["recommendation_label"] == "BUY"
    assert signal["is_actionable_now"] is False
    assert signal["entry"] is None
    assert signal["entry_price"] is None
    assert signal["target_price"] is None
    assert signal["stop_loss_price"] is None
    assert signal["breakout_level"] is None
    assert signal["day_trade"]["entry_price"] is None
    assert signal["day_trade"]["trade_state"] == "STALE — REFRESH REQUIRED"
    assert protected["market_rows"][0]["trade_state"] == "STALE — REFRESH REQUIRED"
    assert protected["long_term"][0]["is_actionable"] is False
    assert protected["long_term"][0]["recommendation_label"] == "BUY"
    assert payload["short_term"][0]["entry_price"] == 100.0


def test_missing_timestamp_fails_closed() -> None:
    protected = apply_scan_freshness_policy(_payload(updated_at=None), now=NOW)

    assert protected["data_status"]["status"] == "stale"
    assert protected["data_status"]["is_actionable"] is False
    assert "timestamp" in protected["data_status"]["block_reason"]


def test_demo_data_is_never_actionable_even_when_recent() -> None:
    payload = _payload(source="demo", updated_at=NOW.isoformat())

    protected = apply_scan_freshness_policy(payload, now=NOW)

    assert protected["data_status"]["status"] == "demo"
    assert protected["data_status"]["is_actionable"] is False
    assert protected["short_term"][0]["trade_state"] == "DEMO — NOT ACTIONABLE"
    assert protected["short_term"][0]["recommendation_label"] == "BUY"


def test_policy_is_idempotent_for_blocked_rows() -> None:
    stale = _payload(updated_at=(NOW - timedelta(days=2)).isoformat())

    first = apply_scan_freshness_policy(stale, now=NOW)
    second = apply_scan_freshness_policy(first, now=NOW)

    assert second["short_term"] == first["short_term"]
    assert second["data_status"]["blocked_actionable_count"] == 1
