from __future__ import annotations

from domain.alerts.selection import mail_gate, select_urgent, select_weekly


def test_weekly_keeps_strong_buys_caps_at_five_and_orders_ties() -> None:
    rows = [
        _long("MSFT", 90, "Strong Buy"),
        _long("AAPL", 90, "Strong Buy"),
        _long("NVDA", 88, "Strong Buy"),
        _long("AMZN", 86, "Strong Buy"),
        _long("META", 84, "Strong Buy"),
        _long("AVGO", 82, "Strong Buy"),
        _long("JPM", 95, "Buy"),
        _long("XOM", 70, "Hold"),
        _long("WMT", 10, "Avoid"),
        _long("COST", 99, "Strong Buy", alternative_signal_applied_impact=7),
    ]
    selection = select_weekly(_live(long_rows=rows))

    assert selection.qualifying_count == 6
    assert [row["ticker"] for row in selection.shown] == ["AAPL", "MSFT", "NVDA", "AMZN", "META"]
    assert "AVGO" not in [row["ticker"] for row in selection.shown]
    assert "JPM" not in [row["ticker"] for row in selection.shown]
    assert "COST" not in [row["ticker"] for row in selection.shown]


def test_weekly_rejects_a_strong_buy_below_80() -> None:
    selection = select_weekly(_live(long_rows=[_long("AAPL", 79, "Strong Buy")]))
    assert selection.shown == ()
    assert selection.qualifying_count == 0


def test_urgent_requires_85_and_drops_ordinary_states() -> None:
    payload = _live(
        short_rows=[
            _short("NVDA", 85),
            _short("AAPL", 84),
            _short("MSFT", 75),
            _short("AMZN", 72),
            _short("META", 90, recommendation_label="Watchlist"),
            _short("JPM", 90, trade_state="WAIT FOR PULLBACK", actionable=False, bucket="waiting"),
            _short("XOM", 90, trade_state="CONFIRMED BREAKDOWN — SELL"),
            _short("COST", 91, alternative_signal_applied_impact=7),
            _short("WMT", 92, relative_strength_applied_impact=1),
            _short("TSM", 93, earnings_intelligence_applied_impact=-2),
        ]
    )

    assert [row["ticker"] for row in select_urgent(payload)] == ["NVDA"]


def test_urgent_caps_at_two_highest_scores() -> None:
    payload = _live(
        short_rows=[
            _short("AVGO", 86),
            _short("AAPL", 90),
            _short("MSFT", 90),
        ]
    )
    assert [row["ticker"] for row in select_urgent(payload)] == ["AAPL", "MSFT"]


def test_gate_allows_only_fresh_actionable_live_scans() -> None:
    assert mail_gate(_live(), "weekly").allowed is True
    assert mail_gate(_live(source="demo", status="demo", actionable=False), "urgent").reason == "demo"
    assert mail_gate(_live(source="cached_real"), "weekly").reason == "cached_real"
    assert mail_gate(_live(status="stale", actionable=False), "urgent").reason == "stale"
    assert mail_gate({"source": "live"}, "weekly").reason == "unavailable"
    assert mail_gate(_live(actionable=False), "urgent").reason == "not_actionable"


def _live(
    *,
    long_rows: list[dict] | None = None,
    short_rows: list[dict] | None = None,
    source: str = "live",
    status: str = "fresh",
    actionable: bool = True,
) -> dict:
    return {
        "source": source,
        "universe_name": "default",
        "universe": ["AAPL", "MSFT"],
        "updated_at": "2026-10-18T17:00:00+00:00",
        "data_status": {
            "status": status,
            "is_actionable": actionable,
            "source": source,
            "captured_at": "2026-10-18T17:00:00+00:00",
        },
        "long_term": long_rows or [],
        "short_term": short_rows or [],
    }


def _long(
    ticker: str,
    score: float,
    label: str,
    **overrides: object,
) -> dict:
    row = {
        "ticker": ticker,
        "company_name": ticker,
        "sector": "Technology",
        "long_term_score": score,
        "recommendation_label": label,
        "confidence": "High",
        "current_price": 100.0,
        "key_strengths": ["Trend is supportive."],
        "key_risks": ["Valuation can compress."],
        "thesis": "Quality compounder.",
        "alternative_signal_applied_impact": 0,
        "relative_strength_applied_impact": 0,
        "earnings_intelligence_applied_impact": 0,
    }
    row.update(overrides)
    return row


def _short(
    ticker: str,
    score: float,
    *,
    recommendation_label: str = "Strong Setup",
    trade_state: str = "ENTER NOW",
    actionable: bool = True,
    bucket: str = "active",
    **overrides: object,
) -> dict:
    row = {
        "ticker": ticker,
        "company_name": ticker,
        "short_term_score": score,
        "recommendation_label": recommendation_label,
        "confidence": "High",
        "trade_state": trade_state,
        "is_actionable_now": actionable,
        "action_block_reason": "",
        "signal_bucket": bucket,
        "setup_type": "Momentum continuation",
        "setup_regime": "Momentum",
        "primary_horizon_label": "1-2 Day Trade",
        "current_price": 100.0,
        "entry_price": 100.0,
        "stop_loss_price": 97.0,
        "target_price": 106.0,
        "reasons": ["Price is holding above VWAP."],
        "invalidation_note": "A close back under VWAP cancels the setup.",
        "day_trade": {"score": score},
        "swing_trade": {"score": 40},
        "alternative_signal_applied_impact": 0,
        "relative_strength_applied_impact": 0,
        "earnings_intelligence_applied_impact": 0,
    }
    row.update(overrides)
    return row
