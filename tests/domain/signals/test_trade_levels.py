from __future__ import annotations

from domain.signals.trade_levels import (
    INVALID_TRADE_LEVEL_STATE,
    apply_scan_trade_level_policy,
    validate_long_trade_levels,
)


def _row(**overrides):
    row = {
        "ticker": "AAPL",
        "current_price": 100.0,
        "primary_horizon_label": "1-2 Day Trade",
        "trade_state": "ENTER NOW",
        "trade_state_tone": "positive",
        "recommendation_label": "Strong Setup",
        "tone": "positive",
        "is_actionable_now": True,
        "entry": "Entry near $100.",
        "target": "Target near $110.",
        "stop_loss": "Stop near $95.",
        "entry_price": 100.0,
        "target_price": 110.0,
        "stop_loss_price": 95.0,
        "day_trade": {
            "trade_state": "ENTER NOW",
            "trade_state_tone": "positive",
            "entry_price": 100.0,
            "target_price": 110.0,
            "stop_loss_price": 95.0,
        },
        "swing_trade": {
            "trade_state": "NO TRADE",
            "trade_state_tone": "neutral",
            "entry_price": 98.0,
            "target_price": 115.0,
            "stop_loss_price": 90.0,
        },
    }
    row.update(overrides)
    return row


def _payload(row):
    return {
        "market_stats": {"actionable_now": 1},
        "short_term": [row],
    }


def test_valid_long_bracket_reports_risk_and_reward() -> None:
    result = validate_long_trade_levels(
        entry_price=100,
        target_price=115,
        stop_loss_price=94,
        reference_price=101,
    )

    assert result.valid is True
    assert result.reason is None
    assert result.risk_pct == 6.0
    assert result.reward_pct == 15.0
    assert result.entry_deviation_pct == 0.9901


def test_zero_entry_and_inverted_stop_are_rejected() -> None:
    result = validate_long_trade_levels(
        entry_price=0,
        target_price=2,
        stop_loss_price=117.89,
    )

    assert result.valid is False
    assert result.reason == "Trade levels must satisfy 0 < stop < entry < target."


def test_implausible_risk_reward_and_reference_jumps_are_rejected() -> None:
    excessive_risk = validate_long_trade_levels(
        entry_price=100,
        target_price=110,
        stop_loss_price=60,
    )
    excessive_reward = validate_long_trade_levels(
        entry_price=100,
        target_price=180,
        stop_loss_price=95,
    )
    detached_entry = validate_long_trade_levels(
        entry_price=70,
        target_price=80,
        stop_loss_price=65,
        reference_price=100,
    )

    assert excessive_risk.valid is False
    assert "35%" in str(excessive_risk.reason)
    assert excessive_reward.valid is False
    assert "75%" in str(excessive_reward.reason)
    assert detached_entry.valid is False
    assert "25%" in str(detached_entry.reason)


def test_invalid_actionable_parent_is_blocked_and_prices_are_removed() -> None:
    invalid = _row(
        entry_price=0.0,
        target_price=2.0,
        stop_loss_price=117.89,
        day_trade={
            "trade_state": "ENTER NOW",
            "trade_state_tone": "positive",
            "entry_price": 0.0,
            "target_price": 2.0,
            "stop_loss_price": 117.89,
        },
    )

    protected = apply_scan_trade_level_policy(_payload(invalid))
    row = protected["short_term"][0]

    assert row["trade_state"] == INVALID_TRADE_LEVEL_STATE
    assert row["recommendation_label"] == INVALID_TRADE_LEVEL_STATE
    assert row["is_actionable_now"] is False
    assert row["entry_price"] is None
    assert row["target_price"] is None
    assert row["stop_loss_price"] is None
    assert row["entry"] is None
    assert row["trade_level_validation"]["valid"] is False
    assert protected["market_stats"]["invalid_trade_level_rows"] == 1
    assert protected["market_stats"]["blocked_invalid_level_signals"] == 1


def test_invalid_alternate_horizon_is_hidden_without_blocking_valid_primary() -> None:
    invalid_swing = {
        "trade_state": "NO TRADE",
        "trade_state_tone": "neutral",
        "entry_price": 0.0,
        "target_price": 2.0,
        "stop_loss_price": 293.17,
    }

    protected = apply_scan_trade_level_policy(_payload(_row(swing_trade=invalid_swing)))
    row = protected["short_term"][0]

    assert row["trade_state"] == "ENTER NOW"
    assert row["is_actionable_now"] is True
    assert row["entry_price"] == 100.0
    assert row["swing_trade"]["entry_price"] is None
    assert row["swing_trade"]["action_block_reason"]
    assert protected["market_stats"]["invalid_trade_level_rows"] == 1
    assert protected["market_stats"]["blocked_invalid_level_signals"] == 0


def test_invalid_primary_horizon_blocks_parent_even_when_parent_copy_is_valid() -> None:
    invalid_day = {
        "trade_state": "ENTER NOW",
        "trade_state_tone": "positive",
        "entry_price": 100.0,
        "target_price": 250.0,
        "stop_loss_price": 95.0,
    }

    protected = apply_scan_trade_level_policy(_payload(_row(day_trade=invalid_day)))
    row = protected["short_term"][0]

    assert row["trade_state"] == INVALID_TRADE_LEVEL_STATE
    assert row["is_actionable_now"] is False
    assert row["entry_price"] is None
    assert protected["market_stats"]["blocked_invalid_level_signals"] == 1


def test_trade_level_policy_is_idempotent() -> None:
    invalid = _row(entry_price=0.0, target_price=2.0, stop_loss_price=117.89)

    first = apply_scan_trade_level_policy(_payload(invalid))
    second = apply_scan_trade_level_policy(first)

    assert second == first
