from __future__ import annotations

import pandas as pd

from application.etf_signal_service import EtfSignalService
from domain.assets import AssetType
from storage.repositories.signal_repository import SignalRepository
from storage.sqlite import initialize_database


def test_etf_signal_generation_tags_asset_type(tmp_path, monkeypatch):
    db_path = tmp_path / "signals.db"
    initialize_database(db_path)
    history = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104],
            "High": [101, 102, 103, 104, 105],
            "Low": [99, 100, 101, 102, 103],
            "Close": [100, 101, 102, 103, 104],
            "Volume": [1_000_000] * 5,
        },
        index=pd.bdate_range("2026-06-01", periods=5),
    )

    class FakeSetup:
        trade_state_label = "ENTER NOW"
        score = 80
        holding_period_label = "5-15d"
        entry_price = 104
        target_price = 110
        stop_loss_price = 100
        setup_type = "momentum"

    class FakeView:
        day_trade = FakeSetup()
        swing_trade = FakeSetup()
        trend_direction = "Bullish"

    class FakeRecommendation:
        label = "Strong Setup"
        confidence = "High"
        invalidation_note = "Break of support"

    monkeypatch.setattr("application.etf_signal_service.build_short_term_view", lambda history: FakeView())
    monkeypatch.setattr("application.etf_signal_service.build_short_term_recommendation", lambda view: FakeRecommendation())
    monkeypatch.setattr(
        "application.etf_signal_service.validate_long_trade_levels",
        lambda **kwargs: type("V", (), {"valid": True})(),
    )

    inserted = EtfSignalService(SignalRepository(db_path)).log_from_history(
        ticker="QQQ",
        name="Invesco QQQ",
        history=history,
        omni_score=72,
        origin="etf_screener",
        source_quality="live",
    )
    signals = SignalRepository(db_path).list_signals(asset_type="ETF")

    assert inserted == 2
    assert all(signal.asset_type == AssetType.ETF for signal in signals)
    assert {signal.strategy_family for signal in signals} == {"short_term_day", "short_term_swing"}
