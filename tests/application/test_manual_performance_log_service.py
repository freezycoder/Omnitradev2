from __future__ import annotations

from datetime import date

import pytest

from application.manual_performance_log_service import (
    DuplicatePerformanceEntryError,
    ManualPerformanceLogService,
)
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository


def test_logs_completed_trade_and_calculates_return(tmp_path):
    db_path = tmp_path / "performance.db"
    service = ManualPerformanceLogService(db_path)

    result = service.log_completed_trade(
        ticker="aapl",
        strategy_family="short_term_swing",
        opened_on=date(2026, 6, 1),
        closed_on=date(2026, 6, 6),
        score=78,
        entry_price=100,
        exit_price=108,
        status="hit_target",
    )

    signals = SignalRepository(db_path).list_signals()
    outcomes = OutcomeRepository(db_path).list_outcomes()

    assert result["ticker"] == "AAPL"
    assert result["realized_return_pct"] == 8.0
    assert result["holding_days"] == 5.0
    assert len(signals) == 1
    assert signals[0].signal_origin == "web_manual"
    assert signals[0].source_quality == "manual"
    assert signals[0].evaluated == 1
    assert len(outcomes) == 1
    assert outcomes[0].status == "hit_target"
    assert outcomes[0].realized_return_pct == 8.0


def test_rejects_duplicate_completed_trade(tmp_path):
    service = ManualPerformanceLogService(tmp_path / "performance.db")
    payload = {
        "ticker": "MSFT",
        "strategy_family": "short_term_day",
        "opened_on": date(2026, 6, 10),
        "closed_on": date(2026, 6, 11),
        "score": 72,
        "entry_price": 400,
        "exit_price": 392,
        "status": "hit_stop",
    }

    service.log_completed_trade(**payload)

    with pytest.raises(DuplicatePerformanceEntryError):
        service.log_completed_trade(**payload)


def test_rejects_close_date_before_open_date(tmp_path):
    service = ManualPerformanceLogService(tmp_path / "performance.db")

    with pytest.raises(ValueError, match="Closed date"):
        service.log_completed_trade(
            ticker="NVDA",
            strategy_family="short_term_swing",
            opened_on=date(2026, 6, 12),
            closed_on=date(2026, 6, 11),
            score=80,
            entry_price=150,
            exit_price=155,
            status="expired",
        )
