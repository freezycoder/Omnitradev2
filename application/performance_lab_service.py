from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from application.entry_trigger_lab_service import EntryTriggerLabService
from application.portfolio_engine_service import PortfolioEngineService
from application.portfolio_history_service import PortfolioHistoryService
from application.portfolio_pnl_service import PortfolioPnlService
from application.strategy_history_service import StrategyHistoryService
from application.strategy_execution_service import StrategyExecutionService
from application.trigger_sensitivity_service import TriggerSensitivityService
from config.performance import (
    EDGE_FILTER_THRESHOLDS,
    LOW_SAMPLE_RESOLVED_THRESHOLD,
    PERFORMANCE_DB_FILE,
    STRATEGY_PRESETS,
    SUPPORTED_SIGNAL_STRATEGIES,
    TURNOVER_LOOKBACK_DAYS,
    estimated_round_trip_cost_pct,
    performance_assumptions_snapshot,
    sample_quality_label,
)
from domain.evaluation.models import PerformanceSummary
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository
from storage.sqlite import connection_scope


class PerformanceLabService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        outcome_repository: OutcomeRepository | None = None,
        entry_trigger_lab_service: EntryTriggerLabService | None = None,
        strategy_execution_service: StrategyExecutionService | None = None,
        portfolio_engine_service: PortfolioEngineService | None = None,
        portfolio_pnl_service: PortfolioPnlService | None = None,
        portfolio_history_service: PortfolioHistoryService | None = None,
        strategy_history_service: StrategyHistoryService | None = None,
        trigger_sensitivity_service: TriggerSensitivityService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._signal_repository = signal_repository or SignalRepository(self._db_path)
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._entry_trigger_lab_service = entry_trigger_lab_service or EntryTriggerLabService(
            signal_repository=self._signal_repository,
            outcome_repository=self._outcome_repository,
            db_path=self._db_path,
        )
        self._strategy_execution_service = strategy_execution_service or StrategyExecutionService(
            signal_repository=self._signal_repository,
            entry_trigger_lab_service=self._entry_trigger_lab_service,
            db_path=self._db_path,
        )
        self._portfolio_engine_service = portfolio_engine_service or PortfolioEngineService(
            strategy_execution_service=self._strategy_execution_service,
            db_path=self._db_path,
        )
        self._portfolio_pnl_service = portfolio_pnl_service or PortfolioPnlService(
            portfolio_engine_service=self._portfolio_engine_service,
            outcome_repository=self._outcome_repository,
            db_path=self._db_path,
        )
        self._portfolio_history_service = portfolio_history_service or PortfolioHistoryService(
            portfolio_pnl_service=self._portfolio_pnl_service,
            db_path=self._db_path,
        )
        self._strategy_history_service = strategy_history_service or StrategyHistoryService(
            strategy_execution_service=self._strategy_execution_service,
            db_path=self._db_path,
        )
        self._trigger_sensitivity_service = trigger_sensitivity_service or TriggerSensitivityService(
            strategy_execution_service=self._strategy_execution_service,
            entry_trigger_lab_service=self._entry_trigger_lab_service,
            portfolio_engine_service=self._portfolio_engine_service,
            db_path=self._db_path,
        )
        self._signal_repository.ensure_schema()
        self._outcome_repository.ensure_schema()

    def get_dashboard_summary(self) -> PerformanceSummary:
        return self._summary_for_strategy(None)

    def get_strategy_summary(self, strategy_family: str) -> PerformanceSummary:
        if strategy_family not in SUPPORTED_SIGNAL_STRATEGIES:
            raise ValueError(f"Unsupported strategy_family: {strategy_family}")
        return self._summary_for_strategy(strategy_family)

    def get_performance_assumptions(self) -> dict[str, object]:
        return performance_assumptions_snapshot()

    def get_performance_risk_context(
        self,
        overall: PerformanceSummary | None = None,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        summary = overall or self.get_dashboard_summary()
        delivered_at = now or datetime.now(UTC)
        delivered_at = (
            delivered_at.astimezone(UTC)
            if delivered_at.tzinfo
            else delivered_at.replace(tzinfo=UTC)
        )
        lookback_days = max(int(TURNOVER_LOOKBACK_DAYS), 1)
        window_start = delivered_at - timedelta(days=lookback_days)

        with connection_scope(self._db_path) as connection:
            turnover_row = connection.execute(
                """
                SELECT COUNT(*) AS signal_count
                FROM signals
                WHERE strategy_family IN ('short_term_day', 'short_term_swing')
                  AND created_at >= ?
                """,
                (window_start.isoformat(),),
            ).fetchone()
            exposure_row = connection.execute(
                """
                SELECT
                    snapshot_at,
                    deployed_capital_weight,
                    cash_reserve_weight,
                    holdings_count,
                    open_holdings_count,
                    resolved_holdings_count
                FROM portfolio_history_snapshots
                WHERE portfolio_name = 'Strategy_v1'
                ORDER BY snapshot_at DESC, snapshot_id DESC
                LIMIT 1
                """
            ).fetchone()

        turnover_signal_count = int(turnover_row["signal_count"] or 0)
        signals_per_week = (turnover_signal_count / lookback_days) * 7.0
        annualized_signals = (turnover_signal_count / lookback_days) * 365.0

        exposure_snapshot_at = str(exposure_row["snapshot_at"]) if exposure_row else None
        exposure_age_hours = None
        if exposure_snapshot_at:
            try:
                captured_at = datetime.fromisoformat(exposure_snapshot_at.replace("Z", "+00:00"))
                captured_at = (
                    captured_at.astimezone(UTC)
                    if captured_at.tzinfo
                    else captured_at.replace(tzinfo=UTC)
                )
                exposure_age_hours = max(
                    0.0,
                    (delivered_at - captured_at).total_seconds() / 3600.0,
                )
            except ValueError:
                exposure_age_hours = None

        return {
            "resolved_signals": summary.resolved_signals,
            "total_signals": summary.total_signals,
            "open_signals": summary.open_signals,
            "sample_quality": sample_quality_label(summary.resolved_signals),
            "win_rate": summary.win_rate,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "max_drawdown_basis": "Cumulative resolved signal returns, not portfolio equity.",
            "risk_flag": summary.risk_flag,
            "turnover_scope": "Logged short-term signals",
            "turnover_lookback_days": lookback_days,
            "turnover_signal_count": turnover_signal_count,
            "signals_per_week": round(signals_per_week, 2),
            "annualized_signals": round(annualized_signals, 2),
            "exposure_basis": "Latest Strategy_v1 portfolio snapshot",
            "exposure_snapshot_at": exposure_snapshot_at,
            "exposure_age_hours": (
                round(exposure_age_hours, 2)
                if exposure_age_hours is not None
                else None
            ),
            "exposure_is_stale": (
                exposure_age_hours is None or exposure_age_hours > 24.0
            ),
            "deployed_capital_weight": (
                float(exposure_row["deployed_capital_weight"])
                if exposure_row
                else None
            ),
            "cash_reserve_weight": (
                float(exposure_row["cash_reserve_weight"])
                if exposure_row
                else None
            ),
            "holdings_count": int(exposure_row["holdings_count"] or 0) if exposure_row else None,
            "open_holdings_count": (
                int(exposure_row["open_holdings_count"] or 0)
                if exposure_row
                else None
            ),
            "resolved_holdings_count": (
                int(exposure_row["resolved_holdings_count"] or 0)
                if exposure_row
                else None
            ),
        }

    def get_score_buckets(self, strategy_family: str | None = None) -> list[dict[str, Any]]:
        ordering = {"80+": 0, "70-79": 1, "60-69": 2, "50-59": 3, "<50": 4}
        expectancy_rows = {
            str(row["score_bucket"]): row
            for row in self._outcome_repository.get_resolved_stats_by_score_bucket(strategy_family)
        }
        query = """
            SELECT
                CASE
                    WHEN s.score >= 80 THEN '80+'
                    WHEN s.score >= 70 THEN '70-79'
                    WHEN s.score >= 60 THEN '60-69'
                    WHEN s.score >= 50 THEN '50-59'
                    ELSE '<50'
                END AS score_bucket,
                SUM(CASE WHEN o.status = 'hit_target' THEN 1 ELSE 0 END) AS target_hits,
                SUM(CASE WHEN o.status = 'hit_stop' THEN 1 ELSE 0 END) AS stop_hits,
                SUM(CASE WHEN o.status = 'expired' THEN 1 ELSE 0 END) AS expired_signals
            FROM signals s
            JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
        """
        params: list[object] = []
        if strategy_family is not None:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        query += " GROUP BY score_bucket"
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        bucket_rows: list[dict[str, Any]] = []
        for row in rows:
            bucket_key = str(row["score_bucket"])
            expectancy_metrics = expectancy_rows.get(bucket_key, {})
            gross_expectancy = expectancy_metrics.get("expectancy_pct")
            estimated_cost_pct = estimated_round_trip_cost_pct()
            bucket_rows.append(
                {
                    "score_bucket": bucket_key,
                    "total_resolved": int(expectancy_metrics.get("total_resolved") or 0),
                    "target_hits": int(row["target_hits"] or 0),
                    "stop_hits": int(row["stop_hits"] or 0),
                    "expired_signals": int(row["expired_signals"] or 0),
                    "wins": int(expectancy_metrics.get("wins") or 0),
                    "losses": int(expectancy_metrics.get("losses") or 0),
                    "flats": int(expectancy_metrics.get("flats") or 0),
                    "win_rate": expectancy_metrics.get("win_rate"),
                    "avg_win_pct": expectancy_metrics.get("avg_win_pct"),
                    "avg_loss_pct": expectancy_metrics.get("avg_loss_pct"),
                    "expectancy_pct": gross_expectancy,
                    "gross_expectancy_pct": gross_expectancy,
                    "estimated_transaction_cost_pct": round(estimated_cost_pct, 4),
                    "net_expectancy_pct": (
                        round(float(gross_expectancy) - estimated_cost_pct, 4)
                        if gross_expectancy is not None
                        else None
                    ),
                    "net_expectancy_modeled": bool(
                        performance_assumptions_snapshot()["net_expectancy_modeled"]
                    ),
                    "risk_adjusted_view": expectancy_metrics.get("risk_adjusted_view"),
                    "avg_return_pct": expectancy_metrics.get("avg_return_pct"),
                    "std_return_pct": expectancy_metrics.get("std_return_pct"),
                    "max_loss_pct": expectancy_metrics.get("max_loss_pct"),
                    "max_drawdown_pct": expectancy_metrics.get("max_drawdown_pct"),
                    "max_consecutive_losses": expectancy_metrics.get("max_consecutive_losses"),
                    "risk_penalty": expectancy_metrics.get("risk_penalty"),
                    "risk_flag": expectancy_metrics.get("risk_flag"),
                }
            )

        bucket_rows.sort(key=lambda item: ordering.get(item["score_bucket"], 99))
        return bucket_rows

    def get_recent_outcomes(self, limit: int = 50) -> list[dict[str, Any]]:
        query = """
            SELECT
                s.created_at,
                s.ticker,
                s.strategy_family,
                s.source_quality,
                s.score,
                s.trade_state,
                s.recommendation_label,
                s.entry_price,
                o.exit_price,
                o.status,
                o.realized_return_pct,
                o.holding_days,
                o.evaluated_at
            FROM signal_outcomes o
            JOIN signals s ON s.signal_id = o.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
            ORDER BY o.evaluated_at DESC
            LIMIT ?
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, (limit,)).fetchall()

        return [
            {
                "created_at": row["created_at"],
                "evaluated_at": row["evaluated_at"],
                "ticker": row["ticker"],
                "strategy": row["strategy_family"],
                "source": row["source_quality"],
                "score": int(round(float(row["score"]))) if row["score"] is not None else None,
                "trade_state": row["trade_state"],
                "recommendation": row["recommendation_label"],
                "entry_price": round(float(row["entry_price"]), 2) if row["entry_price"] is not None else None,
                "exit_price": round(float(row["exit_price"]), 2) if row["exit_price"] is not None else None,
                "status": row["status"],
                "realized_return_pct": round(float(row["realized_return_pct"]), 2) if row["realized_return_pct"] is not None else None,
                "holding_days": round(float(row["holding_days"]), 2) if row["holding_days"] is not None else None,
            }
            for row in rows
        ]

    def get_edge_filter_analysis(self, strategy_family: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for threshold_label, min_score in EDGE_FILTER_THRESHOLDS:
            counts = self._signal_repository.get_signal_counts(strategy_family=strategy_family, min_score=min_score)
            resolved_stats = self._outcome_repository.get_overall_resolved_stats(
                strategy_family=strategy_family,
                min_score=min_score,
            )
            resolved_signals = int(resolved_stats.get("resolved_signals") or 0)
            rows.append(
                {
                    "threshold_label": threshold_label,
                    "min_score": min_score,
                    "total_signals": int(counts.get("total_signals") or 0),
                    "resolved_signals": resolved_signals,
                    "wins": int(resolved_stats.get("wins") or 0),
                    "losses": int(resolved_stats.get("losses") or 0),
                    "flats": int(resolved_stats.get("flats") or 0),
                    "win_rate": resolved_stats.get("win_rate"),
                    "avg_return_pct": resolved_stats.get("avg_return_pct"),
                    "avg_win_pct": resolved_stats.get("avg_win_pct"),
                    "avg_loss_pct": resolved_stats.get("avg_loss_pct"),
                    "expectancy_pct": resolved_stats.get("expectancy_pct"),
                    "risk_adjusted_view": resolved_stats.get("risk_adjusted_view"),
                    "std_return_pct": resolved_stats.get("std_return_pct"),
                    "max_loss_pct": resolved_stats.get("max_loss_pct"),
                    "max_drawdown_pct": resolved_stats.get("max_drawdown_pct"),
                    "max_consecutive_losses": resolved_stats.get("max_consecutive_losses"),
                    "risk_penalty": resolved_stats.get("risk_penalty"),
                    "risk_flag": resolved_stats.get("risk_flag"),
                    "sample_note": (
                        "No resolved sample yet"
                        if resolved_signals == 0
                        else (
                            f"Early sample (<{LOW_SAMPLE_RESOLVED_THRESHOLD} resolved)"
                            if resolved_signals < LOW_SAMPLE_RESOLVED_THRESHOLD
                            else "Established"
                        )
                    ),
                    "low_sample": 0 < resolved_signals < LOW_SAMPLE_RESOLVED_THRESHOLD,
                    "sample_quality": sample_quality_label(resolved_signals),
                }
            )
        return rows

    def get_edge_filter_payload(self) -> dict[str, Any]:
        strategy_payload = {
            "all_short_term": self.get_edge_filter_analysis(None),
            "short_term_day": self.get_edge_filter_analysis("short_term_day"),
            "short_term_swing": self.get_edge_filter_analysis("short_term_swing"),
        }
        best_by_strategy: dict[str, dict[str, Any] | None] = {}
        for strategy_key, rows in strategy_payload.items():
            candidates = [row for row in rows if row["threshold_label"] != "All" and row["expectancy_pct"] is not None]
            established = [row for row in candidates if not row["low_sample"]]
            pool = established or candidates
            best_by_strategy[strategy_key] = max(
                pool,
                key=lambda item: (float(item["expectancy_pct"]), int(item["resolved_signals"])),
            ) if pool else None
        return {
            "threshold_options": [label for label, _ in EDGE_FILTER_THRESHOLDS],
            "low_sample_threshold": LOW_SAMPLE_RESOLVED_THRESHOLD,
            "by_strategy": strategy_payload,
            "best_by_strategy": best_by_strategy,
        }

    def get_edge_discovery_payload(self) -> dict[str, Any]:
        strategy_scope = {
            "all_short_term": None,
            "short_term_day": "short_term_day",
            "short_term_swing": "short_term_swing",
        }
        by_strategy: dict[str, dict[str, Any]] = {}
        for strategy_key, strategy_family in strategy_scope.items():
            rows = self._outcome_repository.get_resolved_stats_by_edge_segment(
                strategy_family=strategy_family,
                min_resolved=LOW_SAMPLE_RESOLVED_THRESHOLD,
            )
            ranked_top = sorted(
                rows,
                key=lambda item: (
                    float(item.get("expectancy_pct") or -9999.0),
                    float(item.get("avg_return_pct") or -9999.0),
                    int(item.get("resolved_signals") or 0),
                ),
                reverse=True,
            )[:10]
            ranked_worst = sorted(
                rows,
                key=lambda item: (
                    float(item.get("expectancy_pct") or 9999.0),
                    float(item.get("avg_return_pct") or 9999.0),
                    -int(item.get("resolved_signals") or 0),
                ),
            )[:10]
            by_strategy[strategy_key] = {
                "segments": rows,
                "top_segments": ranked_top,
                "worst_segments": ranked_worst,
            }
        return {
            "min_resolved": LOW_SAMPLE_RESOLVED_THRESHOLD,
            "by_strategy": by_strategy,
        }

    def get_strategy_presets(self) -> dict[str, dict[str, Any]]:
        return {
            name: {
                "name": preset.name,
                "trade_state": preset.trade_state,
                "min_score": preset.min_score,
                "trend_direction": preset.trend_direction,
                "entry_method": preset.entry_method,
                "pullback_pct": preset.pullback_pct,
                "exit_method": preset.exit_method,
                "notes": preset.notes,
            }
            for name, preset in STRATEGY_PRESETS.items()
        }

    def get_entry_trigger_lab_payload(self) -> dict[str, Any]:
        return {
            "short_term_day": self._entry_trigger_lab_service.build_entry_trigger_payload("short_term_day"),
            "short_term_swing": self._entry_trigger_lab_service.build_entry_trigger_payload("short_term_swing"),
        }

    def get_strategy_v1_execution_payload(self) -> dict[str, Any]:
        return self._strategy_execution_service.build_strategy_v1_execution_payload()

    def get_strategy_v1_portfolio_payload(self) -> dict[str, Any]:
        return self._portfolio_engine_service.build_strategy_v1_portfolio_payload()

    def get_strategy_v1_benchmark_portfolio_payload(self) -> dict[str, Any]:
        return self._portfolio_engine_service.build_strategy_v1_benchmark_portfolio_payload()

    def get_strategy_v1_portfolio_pnl_payload(self) -> dict[str, Any]:
        return self._portfolio_pnl_service.build_strategy_v1_portfolio_pnl_payload()

    def get_strategy_v1_benchmark_portfolio_pnl_payload(self) -> dict[str, Any]:
        return self._portfolio_pnl_service.build_strategy_v1_benchmark_portfolio_pnl_payload()

    def get_strategy_v1_portfolio_history_payload(self) -> dict[str, Any]:
        return self._portfolio_history_service.build_strategy_v1_history_payload()

    def get_strategy_v1_strategy_history_payload(self) -> dict[str, Any]:
        return self._strategy_history_service.build_strategy_v1_history_payload()

    def get_strategy_v1_capture_metrics_payload(self) -> dict[str, Any]:
        execution_payload = self.get_strategy_v1_execution_payload()
        portfolio_payload = self.get_strategy_v1_portfolio_payload()
        portfolio_pnl_payload = self.get_strategy_v1_portfolio_pnl_payload()

        eligible_rows = [
            row
            for row in execution_payload.get("deduplicated_signals", [])
            if str(row.get("trigger_status") or "").lower() in {"triggered", "waiting"}
            and self._expectancy_for_eligibility(row) > 0
            and float(row.get("position_size") or 0.0) > 0
        ]
        eligible_signals_count = len(eligible_rows)
        triggered_signals_count = sum(
            1 for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "triggered"
        )
        waiting_signals_count = sum(
            1 for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "waiting"
        )
        holdings_count = int(portfolio_payload.get("summary", {}).get("holdings_count") or 0)
        deployed_capital_weight = float(portfolio_pnl_payload.get("summary", {}).get("deployed_capital_weight") or 0.0)
        denominator = max(eligible_signals_count, 1)
        max_deployable_from_triggered = triggered_signals_count * self._portfolio_engine_service.MAX_SINGLE_NAME_WEIGHT
        capital_capture_ratio = (
            min(1.0, deployed_capital_weight / max(max_deployable_from_triggered, 1e-9))
            if max_deployable_from_triggered > 0
            else 0.0
        )

        return {
            "eligible_signals_count": eligible_signals_count,
            "triggered_signals_count": triggered_signals_count,
            "waiting_signals_count": waiting_signals_count,
            "holdings_count": holdings_count,
            "deployed_capital_weight": round(deployed_capital_weight, 4),
            "trigger_rate": round(triggered_signals_count / denominator, 4),
            "wait_ratio": round(waiting_signals_count / denominator, 4),
            "deployment_efficiency": round(deployed_capital_weight / denominator, 4),
            "edge_capture_ratio": round(holdings_count / denominator, 4),
            "capital_capture_ratio": round(capital_capture_ratio, 4),
        }

    def get_trigger_sensitivity_payload(self) -> dict[str, Any]:
        return self._trigger_sensitivity_service.build_trigger_sensitivity_payload()

    def build_dashboard_payload(self) -> dict[str, Any]:
        # Compute expensive payloads once and reuse them to avoid redundant computation.
        execution_payload = self.get_strategy_v1_execution_payload()
        portfolio_payload = self.get_strategy_v1_portfolio_payload()
        portfolio_pnl_payload = self.get_strategy_v1_portfolio_pnl_payload()
        benchmark_portfolio_pnl_payload = self.get_strategy_v1_benchmark_portfolio_pnl_payload()
        return {
            "overall": self.get_dashboard_summary(),
            "by_strategy": {
                strategy: self.get_strategy_summary(strategy) for strategy in SUPPORTED_SIGNAL_STRATEGIES
            },
            "score_buckets": self.get_score_buckets(),
            "edge_filter": self.get_edge_filter_payload(),
            "edge_discovery": self.get_edge_discovery_payload(),
            "entry_trigger_lab": self.get_entry_trigger_lab_payload(),
            "strategy_v1_execution": execution_payload,
            "strategy_v1_portfolio": portfolio_payload,
            "strategy_v1_benchmark_portfolio": self.get_strategy_v1_benchmark_portfolio_payload(),
            "strategy_v1_portfolio_pnl": portfolio_pnl_payload,
            "strategy_v1_benchmark_portfolio_pnl": benchmark_portfolio_pnl_payload,
            "strategy_v1_capture_metrics": self._capture_metrics_from_payloads(
                execution_payload, portfolio_payload, portfolio_pnl_payload
            ),
            "trigger_sensitivity": self.get_trigger_sensitivity_payload(),
            "strategy_v1_strategy_history": self._strategy_history_service.build_strategy_v1_history_payload(
                execution_payload=execution_payload
            ),
            "strategy_v1_portfolio_history": self._portfolio_history_service.build_strategy_v1_history_payload(
                pnl_payload=portfolio_pnl_payload,
                benchmark_pnl_payload=benchmark_portfolio_pnl_payload,
            ),
            "strategy_presets": self.get_strategy_presets(),
            "recent_outcomes": self.get_recent_outcomes(limit=25),
        }

    def _capture_metrics_from_payloads(
        self,
        execution_payload: dict[str, Any],
        portfolio_payload: dict[str, Any],
        portfolio_pnl_payload: dict[str, Any],
    ) -> dict[str, Any]:
        eligible_rows = [
            row
            for row in execution_payload.get("deduplicated_signals", [])
            if str(row.get("trigger_status") or "").lower() in {"triggered", "waiting"}
            and self._expectancy_for_eligibility(row) > 0
            and float(row.get("position_size") or 0.0) > 0
        ]
        eligible_signals_count = len(eligible_rows)
        triggered_signals_count = sum(
            1 for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "triggered"
        )
        waiting_signals_count = sum(
            1 for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "waiting"
        )
        holdings_count = int(portfolio_payload.get("summary", {}).get("holdings_count") or 0)
        deployed_capital_weight = float(
            portfolio_pnl_payload.get("summary", {}).get("deployed_capital_weight") or 0.0
        )
        denominator = max(eligible_signals_count, 1)
        max_deployable_from_triggered = triggered_signals_count * self._portfolio_engine_service.MAX_SINGLE_NAME_WEIGHT
        capital_capture_ratio = (
            min(1.0, deployed_capital_weight / max(max_deployable_from_triggered, 1e-9))
            if max_deployable_from_triggered > 0
            else 0.0
        )
        return {
            "eligible_signals_count": eligible_signals_count,
            "triggered_signals_count": triggered_signals_count,
            "waiting_signals_count": waiting_signals_count,
            "holdings_count": holdings_count,
            "deployed_capital_weight": round(deployed_capital_weight, 4),
            "trigger_rate": round(triggered_signals_count / denominator, 4),
            "wait_ratio": round(waiting_signals_count / denominator, 4),
            "deployment_efficiency": round(deployed_capital_weight / denominator, 4),
            "edge_capture_ratio": round(holdings_count / denominator, 4),
            "capital_capture_ratio": round(capital_capture_ratio, 4),
        }

    @staticmethod
    def _expectancy_for_eligibility(row: dict[str, Any]) -> float:
        net_expectancy = row.get("net_historical_expectancy_pct")
        if net_expectancy is not None:
            return float(net_expectancy)
        return float(row.get("historical_cohort_expectancy_pct") or 0.0)

    def _summary_for_strategy(self, strategy_family: str | None) -> PerformanceSummary:
        query = """
            SELECT
                COUNT(*) AS total_signals,
                SUM(CASE WHEN o.status IS NULL THEN 1 ELSE 0 END) AS open_signals,
                SUM(CASE WHEN o.status = 'hit_target' THEN 1 ELSE 0 END) AS target_hits,
                SUM(CASE WHEN o.status = 'hit_stop' THEN 1 ELSE 0 END) AS stop_hits,
                SUM(CASE WHEN o.status = 'expired' THEN 1 ELSE 0 END) AS expired_signals
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
        """
        params: list[object] = []
        if strategy_family is not None:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)

        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, params).fetchone()

        resolved_stats = self._outcome_repository.get_overall_resolved_stats(strategy_family)
        gross_expectancy = resolved_stats.get("expectancy_pct")
        assumptions = performance_assumptions_snapshot()
        estimated_cost_pct = estimated_round_trip_cost_pct()
        total_signals = int(row["total_signals"] or 0)
        target_hits = int(row["target_hits"] or 0)
        return PerformanceSummary(
            strategy_family=strategy_family or "all_short_term",
            total_signals=total_signals,
            resolved_signals=int(resolved_stats.get("resolved_signals") or 0),
            total_resolved=int(resolved_stats.get("total_resolved") or 0),
            open_signals=int(row["open_signals"] or 0),
            target_hits=target_hits,
            stop_hits=int(row["stop_hits"] or 0),
            expired_signals=int(row["expired_signals"] or 0),
            wins=int(resolved_stats.get("wins") or 0),
            losses=int(resolved_stats.get("losses") or 0),
            flats=int(resolved_stats.get("flats") or 0),
            win_rate=resolved_stats.get("win_rate"),
            loss_rate=resolved_stats.get("loss_rate"),
            avg_win_pct=resolved_stats.get("avg_win_pct"),
            avg_loss_pct=resolved_stats.get("avg_loss_pct"),
            avg_return_pct=resolved_stats.get("avg_return_pct"),
            median_return_pct=None,
            expectancy_pct=gross_expectancy,
            gross_expectancy_pct=gross_expectancy,
            estimated_transaction_cost_pct=round(estimated_cost_pct, 4),
            net_expectancy_pct=(
                round(float(gross_expectancy) - estimated_cost_pct, 4)
                if gross_expectancy is not None
                else None
            ),
            net_expectancy_modeled=bool(assumptions["net_expectancy_modeled"]),
            reporting_basis=str(assumptions["reporting_basis"]),
            risk_adjusted_view=resolved_stats.get("risk_adjusted_view"),
            std_return_pct=resolved_stats.get("std_return_pct"),
            max_loss_pct=resolved_stats.get("max_loss_pct"),
            max_drawdown_pct=resolved_stats.get("max_drawdown_pct"),
            max_consecutive_losses=int(resolved_stats.get("max_consecutive_losses") or 0),
            risk_penalty=resolved_stats.get("risk_penalty"),
            risk_flag=resolved_stats.get("risk_flag"),
        )


__all__ = ["PerformanceLabService"]
