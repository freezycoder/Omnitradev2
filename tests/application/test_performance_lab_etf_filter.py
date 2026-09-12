from __future__ import annotations

from datetime import date

from application.manual_performance_log_service import ManualPerformanceLogService
from application.performance_lab_service import PerformanceLabService
from domain.assets import AssetType
from domain.signals.models import SignalRecord, build_dedupe_key, normalize_timestamp
from storage.repositories.signal_repository import SignalRepository
from storage.sqlite import initialize_database


def test_performance_lab_filters_etf_signals(tmp_path):
    db_path = tmp_path / "perf.db"
    initialize_database(db_path)
    service = ManualPerformanceLogService(db_path)
    service.log_completed_trade(
        ticker="AAPL",
        strategy_family="short_term_swing",
        opened_on=date(2026, 6, 1),
        closed_on=date(2026, 6, 6),
        score=78,
        entry_price=100,
        exit_price=108,
        status="hit_target",
    )
    repo = SignalRepository(db_path)
    created_at = normalize_timestamp("2026-06-02T00:00:00+00:00")
    repo.insert_signal(
        SignalRecord(
            signal_id="etf-1",
            dedupe_key=build_dedupe_key(
                ticker="QQQ",
                strategy_family="short_term_swing",
                source_quality="live",
                signal_origin="etf_screener",
                created_at=created_at,
                trade_state="ENTER NOW",
                recommendation_label="Watchlist",
                entry_price=400,
                asset_type=AssetType.ETF,
            ),
            created_at=created_at,
            ticker="QQQ",
            company_name="QQQ",
            strategy_family="short_term_swing",
            signal_origin="etf_screener",
            source_quality="live",
            model_version="test",
            recommendation_label="Watchlist",
            recommendation_confidence="Moderate",
            trade_state="ENTER NOW",
            holding_period_label="15d",
            score=70,
            entry_price=400,
            target_price=420,
            stop_loss_price=390,
            trend_direction="Bullish",
            setup_type="momentum",
            invalidation_note=None,
            accounting_quality_score=None,
            shenanigan_risk_score=None,
            accounting_data_completeness_score=None,
            accounting_assessment_confidence=None,
            news_score=None,
            news_impact=None,
            feature_snapshot_json="{}",
            evaluated=0,
            asset_type=AssetType.ETF,
        )
    )

    lab = PerformanceLabService(db_path=db_path)
    stock_summary = lab.get_dashboard_summary(asset_type="STOCK")
    etf_summary = lab.get_dashboard_summary(asset_type="ETF")
    recent_etf = lab.get_recent_outcomes(asset_type="ETF")

    assert stock_summary.total_signals == 1
    assert etf_summary.total_signals == 1
    assert recent_etf == []
