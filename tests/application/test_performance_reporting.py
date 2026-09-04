from __future__ import annotations

from datetime import UTC, datetime, timedelta

from application.performance_lab_service import PerformanceLabService
from config.performance import performance_assumptions_snapshot
from domain.evaluation.models import PerformanceSummary
from storage.sqlite import connection_scope


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def _summary() -> PerformanceSummary:
    return PerformanceSummary(
        strategy_family="all_short_term",
        total_signals=12,
        resolved_signals=10,
        total_resolved=10,
        open_signals=2,
        target_hits=6,
        stop_hits=4,
        expired_signals=0,
        wins=6,
        losses=4,
        flats=0,
        win_rate=60.0,
        loss_rate=40.0,
        avg_win_pct=3.0,
        avg_loss_pct=2.0,
        avg_return_pct=1.0,
        median_return_pct=None,
        expectancy_pct=1.0,
        gross_expectancy_pct=1.0,
        estimated_transaction_cost_pct=0.0,
        net_expectancy_pct=1.0,
        net_expectancy_modeled=False,
        reporting_basis="gross_before_costs",
        risk_adjusted_view=0.5,
        std_return_pct=2.0,
        max_loss_pct=4.0,
        max_drawdown_pct=6.5,
        max_consecutive_losses=2,
        risk_penalty=0.2,
        risk_flag="Watch",
    )


def _insert_signal(connection, signal_id: str, created_at: datetime) -> None:
    connection.execute(
        """
        INSERT INTO signals (
            signal_id,
            dedupe_key,
            created_at,
            ticker,
            strategy_family,
            signal_origin,
            source_quality,
            model_version,
            recommendation_label,
            recommendation_confidence,
            score,
            feature_snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id,
            signal_id,
            created_at.isoformat(),
            "AAPL",
            "short_term_day",
            "test",
            "live",
            "test",
            "Strong Setup",
            "High",
            80.0,
            "{}",
        ),
    )


def test_zero_cost_configuration_is_labeled_gross_before_costs() -> None:
    assumptions = performance_assumptions_snapshot()

    assert assumptions["reporting_basis"] == "gross_before_costs"
    assert assumptions["result_label"] == "Gross, before costs"
    assert assumptions["transaction_costs_configured"] is False
    assert assumptions["net_expectancy_modeled"] is False
    assert assumptions["estimated_round_trip_cost_pct"] == 0.0
    assert assumptions["cost_filter_enabled"] is False
    assert assumptions["reward_risk_filter_enabled"] is False
    assert assumptions["time_stop_enabled"] is False
    assert assumptions["warning"]


def test_risk_context_combines_sample_drawdown_turnover_and_exposure(tmp_path) -> None:
    service = PerformanceLabService(db_path=tmp_path / "performance.db")
    recent_one = NOW - timedelta(days=1)
    recent_two = NOW - timedelta(days=20)
    old_signal = NOW - timedelta(days=120)

    with connection_scope(tmp_path / "performance.db") as connection:
        _insert_signal(connection, "recent-1", recent_one)
        _insert_signal(connection, "recent-2", recent_two)
        _insert_signal(connection, "old", old_signal)
        connection.execute(
            """
            INSERT INTO portfolio_history_snapshots (
                portfolio_name,
                snapshot_at,
                deployed_capital_weight,
                cash_reserve_weight,
                realized_pnl_pct,
                unrealized_pnl_pct,
                total_portfolio_pnl_pct,
                weighted_hit_rate,
                holdings_count,
                open_holdings_count,
                resolved_holdings_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Strategy_v1",
                (NOW - timedelta(hours=12)).isoformat(),
                0.4,
                0.6,
                1.0,
                2.0,
                3.0,
                50.0,
                2,
                1,
                1,
            ),
        )

    context = service.get_performance_risk_context(_summary(), now=NOW)

    assert context["resolved_signals"] == 10
    assert context["sample_quality"] == "Weak"
    assert context["max_drawdown_pct"] == 6.5
    assert context["turnover_signal_count"] == 2
    assert context["signals_per_week"] == 0.16
    assert context["annualized_signals"] == 8.11
    assert context["deployed_capital_weight"] == 0.4
    assert context["cash_reserve_weight"] == 0.6
    assert context["holdings_count"] == 2
    assert context["exposure_age_hours"] == 12.0
    assert context["exposure_is_stale"] is False
