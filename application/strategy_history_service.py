from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from application.strategy_execution_service import StrategyExecutionService
from config.performance import PERFORMANCE_DB_FILE, PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES
from storage.sqlite import connection_scope, initialize_database


class StrategyHistoryService:
    def __init__(
        self,
        strategy_execution_service: StrategyExecutionService | None = None,
        db_path: Path | None = None,
        min_snapshot_minutes: int = PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._strategy_execution_service = strategy_execution_service or StrategyExecutionService(db_path=self._db_path)
        self._min_snapshot_minutes = max(0, int(min_snapshot_minutes))
        # Schema bootstrap is centralised at app startup — see app.py.

    def build_strategy_v1_history_payload(
        self,
        record_snapshot: bool = True,
        execution_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if execution_payload is None:
            execution_payload = self._strategy_execution_service.build_strategy_v1_execution_payload()
        if record_snapshot:
            self.record_snapshot_from_payload("Strategy_v1", execution_payload)
        snapshots = self.load_snapshots("Strategy_v1")
        return {
            "strategy_name": "Strategy_v1",
            "summary": self._history_summary(snapshots),
            "snapshots": snapshots,
            "trigger_series": [
                {
                    "timestamp": row["snapshot_at"],
                    "triggered_signals_count": row["triggered_signals_count"],
                    "waiting_signals_count": row["waiting_signals_count"],
                }
                for row in snapshots
            ],
            "quality_series": [
                {
                    "timestamp": row["snapshot_at"],
                    "cohort_expectancy_pct": row["cohort_expectancy_pct"],
                    "average_edge_score": row["average_edge_score"],
                    "average_position_size": row["average_position_size"],
                    "average_risk_penalty": row["average_risk_penalty"],
                }
                for row in snapshots
            ],
        }

    def record_snapshot_from_payload(
        self,
        strategy_name: str,
        execution_payload: dict[str, Any],
        *,
        force: bool = False,
    ) -> bool:
        now = datetime.now(tz=UTC)
        if not force and self._is_within_snapshot_window(strategy_name, now):
            return False

        active_rows = [
            row
            for row in execution_payload.get("deduplicated_signals", [])
            if str(row.get("trigger_status") or "").lower() in {"triggered", "waiting"}
        ]
        eligible_rows = [
            row
            for row in active_rows
            if self._expectancy_for_eligibility(row) > 0
            and float(row.get("position_size") or 0.0) > 0
        ]
        historical_expectancy = execution_payload.get("historical_expectancy") or {}
        payload = {
            "strategy_name": strategy_name,
            "snapshot_at": now.isoformat(),
            "triggered_signals_count": int(
                execution_payload.get("counts", {}).get("execution_deduplicated_triggered_signals") or 0
            ),
            "waiting_signals_count": sum(
                1 for row in active_rows if str(row.get("trigger_status") or "").lower() == "waiting"
            ),
            "eligible_signals_count": len(eligible_rows),
            "cohort_expectancy_pct": self._as_float(historical_expectancy.get("expectancy_pct")),
            "cohort_win_rate": self._as_float(historical_expectancy.get("win_rate")),
            "average_edge_score": self._average(active_rows, "edge_quality_score"),
            "average_position_size": self._average(active_rows, "position_size"),
            "average_risk_penalty": self._average(active_rows, "historical_cohort_risk_penalty"),
        }
        query = """
            INSERT INTO strategy_history_snapshots (
                strategy_name,
                snapshot_at,
                triggered_signals_count,
                waiting_signals_count,
                eligible_signals_count,
                cohort_expectancy_pct,
                cohort_win_rate,
                average_edge_score,
                average_position_size,
                average_risk_penalty
            ) VALUES (
                :strategy_name,
                :snapshot_at,
                :triggered_signals_count,
                :waiting_signals_count,
                :eligible_signals_count,
                :cohort_expectancy_pct,
                :cohort_win_rate,
                :average_edge_score,
                :average_position_size,
                :average_risk_penalty
            )
        """
        with connection_scope(self._db_path) as connection:
            connection.execute(query, payload)
        return True

    def load_snapshots(self, strategy_name: str) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM strategy_history_snapshots
            WHERE strategy_name = ?
            ORDER BY snapshot_at ASC, snapshot_id ASC
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, (strategy_name,)).fetchall()
        return [
            {
                "snapshot_id": int(row["snapshot_id"]),
                "strategy_name": row["strategy_name"],
                "snapshot_at": row["snapshot_at"],
                "triggered_signals_count": int(row["triggered_signals_count"] or 0),
                "waiting_signals_count": int(row["waiting_signals_count"] or 0),
                "eligible_signals_count": int(row["eligible_signals_count"] or 0),
                "cohort_expectancy_pct": self._as_float(row["cohort_expectancy_pct"]),
                "cohort_win_rate": self._as_float(row["cohort_win_rate"]),
                "average_edge_score": self._as_float(row["average_edge_score"]),
                "average_position_size": self._as_float(row["average_position_size"]),
                "average_risk_penalty": self._as_float(row["average_risk_penalty"]),
            }
            for row in rows
        ]

    def _is_within_snapshot_window(self, strategy_name: str, now: datetime) -> bool:
        query = """
            SELECT snapshot_at
            FROM strategy_history_snapshots
            WHERE strategy_name = ?
            ORDER BY snapshot_at DESC, snapshot_id DESC
            LIMIT 1
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (strategy_name,)).fetchone()
        if row is None or row["snapshot_at"] is None:
            return False
        last_snapshot_at = datetime.fromisoformat(str(row["snapshot_at"]))
        return now - last_snapshot_at < timedelta(minutes=self._min_snapshot_minutes)

    def _history_summary(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        if not snapshots:
            return {
                "latest_triggered_count": 0,
                "latest_waiting_count": 0,
                "latest_cohort_expectancy_pct": None,
                "latest_average_edge_score": None,
                "snapshots_count": 0,
            }
        latest = snapshots[-1]
        return {
            "latest_triggered_count": latest.get("triggered_signals_count", 0),
            "latest_waiting_count": latest.get("waiting_signals_count", 0),
            "latest_cohort_expectancy_pct": latest.get("cohort_expectancy_pct"),
            "latest_average_edge_score": latest.get("average_edge_score"),
            "snapshots_count": len(snapshots),
        }

    @staticmethod
    def _expectancy_for_eligibility(row: dict[str, Any]) -> float:
        net_expectancy = row.get("net_historical_expectancy_pct")
        if net_expectancy is not None:
            return float(net_expectancy)
        return float(row.get("historical_cohort_expectancy_pct") or 0.0)

    @staticmethod
    def _average(rows: list[dict[str, Any]], key: str) -> float | None:
        values = [float(row.get(key)) for row in rows if row.get(key) is not None]
        if not values:
            return None
        return round(mean(values), 2)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


__all__ = ["StrategyHistoryService"]
