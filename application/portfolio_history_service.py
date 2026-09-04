from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from application.portfolio_pnl_service import PortfolioPnlService
from config.performance import PERFORMANCE_DB_FILE, PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES
from storage.sqlite import connection_scope, initialize_database


class PortfolioHistoryService:
    ACTIVE_PORTFOLIO_NAME = "Strategy_v1"
    BENCHMARK_PORTFOLIO_NAME = "Strategy_v1_Benchmark"

    def __init__(
        self,
        portfolio_pnl_service: PortfolioPnlService | None = None,
        db_path: Path | None = None,
        min_snapshot_minutes: int = PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._portfolio_pnl_service = portfolio_pnl_service or PortfolioPnlService(db_path=self._db_path)
        self._min_snapshot_minutes = max(0, int(min_snapshot_minutes))
        # Schema bootstrap is centralised at app startup — see app.py.

    def build_strategy_v1_history_payload(
        self,
        record_snapshot: bool = True,
        pnl_payload: dict[str, Any] | None = None,
        benchmark_pnl_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if pnl_payload is None:
            pnl_payload = self._portfolio_pnl_service.build_strategy_v1_portfolio_pnl_payload()
        if benchmark_pnl_payload is None:
            benchmark_pnl_payload = self._portfolio_pnl_service.build_strategy_v1_benchmark_portfolio_pnl_payload()
        existing_active_snapshots = self.load_snapshots(self.ACTIVE_PORTFOLIO_NAME)
        existing_benchmark_snapshots = self.load_snapshots(self.BENCHMARK_PORTFOLIO_NAME)
        if record_snapshot:
            now = datetime.now(tz=UTC)
            needs_bootstrap_pair = len(existing_benchmark_snapshots) == 0
            if needs_bootstrap_pair or not self._is_within_snapshot_window(self.ACTIVE_PORTFOLIO_NAME, now):
                self.record_snapshot_from_payload(
                    self.ACTIVE_PORTFOLIO_NAME,
                    pnl_payload,
                    force=True,
                    snapshot_at=now,
                )
                self.record_snapshot_from_payload(
                    self.BENCHMARK_PORTFOLIO_NAME,
                    benchmark_pnl_payload,
                    force=True,
                    snapshot_at=now,
                )
        snapshots = self.load_snapshots(self.ACTIVE_PORTFOLIO_NAME)
        benchmark_snapshots = self.load_snapshots(self.BENCHMARK_PORTFOLIO_NAME)
        comparison_snapshots = self._comparison_snapshots(snapshots, benchmark_snapshots)
        return {
            "portfolio_name": self.ACTIVE_PORTFOLIO_NAME,
            "summary": self._history_summary(snapshots),
            "snapshots": snapshots,
            "benchmark_summary": self._history_summary(benchmark_snapshots),
            "benchmark_snapshots": benchmark_snapshots,
            "comparison_summary": self._comparison_summary(comparison_snapshots),
            "comparison_curve": comparison_snapshots,
            "equity_curve": [
                {
                    "timestamp": row["snapshot_at"],
                    "strategy_weighted_pnl_pct": row["total_portfolio_pnl_pct"],
                    "equal_weight_baseline_pnl_pct": row["equal_weight_baseline_pnl_pct"],
                    "immediate_entry_baseline_pnl_pct": row["immediate_entry_baseline_pnl_pct"],
                }
                for row in snapshots
            ],
            "drawdown_curve": self._drawdown_curve(snapshots),
            "capital_curve": [
                {
                    "timestamp": row["snapshot_at"],
                    "deployed_capital_weight": row["deployed_capital_weight"],
                    "cash_reserve_weight": row["cash_reserve_weight"],
                }
                for row in snapshots
            ],
        }

    def record_snapshot_from_payload(
        self,
        portfolio_name: str,
        pnl_payload: dict[str, Any],
        *,
        force: bool = False,
        snapshot_at: datetime | None = None,
    ) -> bool:
        now = snapshot_at or datetime.now(tz=UTC)
        if not force and self._is_within_snapshot_window(portfolio_name, now):
            return False

        summary = pnl_payload.get("summary", {})
        baseline_map = {
            str(row.get("Baseline") or ""): row for row in pnl_payload.get("baseline_comparison", [])
        }
        payload = {
            "portfolio_name": portfolio_name,
            "snapshot_at": now.isoformat(),
            "deployed_capital_weight": float(summary.get("deployed_capital_weight") or 0.0),
            "cash_reserve_weight": float(summary.get("cash_reserve_weight") or 0.0),
            "realized_pnl_pct": self._as_float(summary.get("realized_pnl_pct")),
            "unrealized_pnl_pct": self._as_float(summary.get("unrealized_pnl_pct")),
            "total_portfolio_pnl_pct": self._as_float(summary.get("total_portfolio_pnl_pct")),
            "weighted_hit_rate": self._as_float(summary.get("weighted_hit_rate")),
            "holdings_count": int(summary.get("holdings_count") or 0),
            "open_holdings_count": int(summary.get("open_holdings") or 0),
            "resolved_holdings_count": int(summary.get("resolved_holdings") or 0),
            "equal_weight_baseline_pnl_pct": self._as_float(
                baseline_map.get("Equal Weight Baseline", {}).get("Total PnL")
            ),
            "immediate_entry_baseline_pnl_pct": self._as_float(
                baseline_map.get("Immediate Entry Baseline", {}).get("Total PnL")
            ),
        }
        query = """
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
                resolved_holdings_count,
                equal_weight_baseline_pnl_pct,
                immediate_entry_baseline_pnl_pct
            ) VALUES (
                :portfolio_name,
                :snapshot_at,
                :deployed_capital_weight,
                :cash_reserve_weight,
                :realized_pnl_pct,
                :unrealized_pnl_pct,
                :total_portfolio_pnl_pct,
                :weighted_hit_rate,
                :holdings_count,
                :open_holdings_count,
                :resolved_holdings_count,
                :equal_weight_baseline_pnl_pct,
                :immediate_entry_baseline_pnl_pct
            )
        """
        with connection_scope(self._db_path) as connection:
            connection.execute(query, payload)
        return True

    def load_snapshots(self, portfolio_name: str) -> list[dict[str, Any]]:
        query = """
            SELECT *
            FROM portfolio_history_snapshots
            WHERE portfolio_name = ?
            ORDER BY snapshot_at ASC, snapshot_id ASC
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, (portfolio_name,)).fetchall()
        return [
            {
                "snapshot_id": int(row["snapshot_id"]),
                "portfolio_name": row["portfolio_name"],
                "snapshot_at": row["snapshot_at"],
                "deployed_capital_weight": float(row["deployed_capital_weight"] or 0.0),
                "cash_reserve_weight": float(row["cash_reserve_weight"] or 0.0),
                "realized_pnl_pct": self._as_float(row["realized_pnl_pct"]),
                "unrealized_pnl_pct": self._as_float(row["unrealized_pnl_pct"]),
                "total_portfolio_pnl_pct": self._as_float(row["total_portfolio_pnl_pct"]),
                "weighted_hit_rate": self._as_float(row["weighted_hit_rate"]),
                "holdings_count": int(row["holdings_count"] or 0),
                "open_holdings_count": int(row["open_holdings_count"] or 0),
                "resolved_holdings_count": int(row["resolved_holdings_count"] or 0),
                "equal_weight_baseline_pnl_pct": self._as_float(row["equal_weight_baseline_pnl_pct"]),
                "immediate_entry_baseline_pnl_pct": self._as_float(row["immediate_entry_baseline_pnl_pct"]),
            }
            for row in rows
        ]

    def _is_within_snapshot_window(self, portfolio_name: str, now: datetime) -> bool:
        query = """
            SELECT snapshot_at
            FROM portfolio_history_snapshots
            WHERE portfolio_name = ?
            ORDER BY snapshot_at DESC, snapshot_id DESC
            LIMIT 1
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (portfolio_name,)).fetchone()
        if row is None or row["snapshot_at"] is None:
            return False
        last_snapshot_at = datetime.fromisoformat(str(row["snapshot_at"]))
        return now - last_snapshot_at < timedelta(minutes=self._min_snapshot_minutes)

    def _history_summary(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        if not snapshots:
            return {
                "cumulative_return_pct": None,
                "max_drawdown_pct": None,
                "average_deployed_capital_weight": None,
                "latest_cash_reserve_weight": None,
                "snapshots_count": 0,
            }
        latest = snapshots[-1]
        deployed_values = [row["deployed_capital_weight"] for row in snapshots]
        return {
            "cumulative_return_pct": latest.get("total_portfolio_pnl_pct"),
            "max_drawdown_pct": self._max_drawdown_pct(
                [row.get("total_portfolio_pnl_pct") for row in snapshots if row.get("total_portfolio_pnl_pct") is not None]
            ),
            "average_deployed_capital_weight": round(mean(deployed_values), 4) if deployed_values else None,
            "latest_cash_reserve_weight": latest.get("cash_reserve_weight"),
            "snapshots_count": len(snapshots),
        }

    def _drawdown_curve(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        drawdowns: list[dict[str, Any]] = []
        running_peak = None
        for row in snapshots:
            total_pnl = row.get("total_portfolio_pnl_pct")
            if total_pnl is None:
                continue
            running_peak = total_pnl if running_peak is None else max(running_peak, total_pnl)
            drawdowns.append(
                {
                    "timestamp": row["snapshot_at"],
                    "drawdown_pct": round(total_pnl - running_peak, 2),
                }
            )
        return drawdowns

    def _comparison_snapshots(
        self,
        active_snapshots: list[dict[str, Any]],
        benchmark_snapshots: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        paired_rows: list[dict[str, Any]] = []
        benchmark_by_timestamp = {
            str(row["snapshot_at"]): row
            for row in benchmark_snapshots
        }
        for active_row in active_snapshots:
            benchmark_row = benchmark_by_timestamp.get(str(active_row["snapshot_at"]))
            if benchmark_row is None:
                continue
            active_total_pnl = self._as_float(active_row.get("total_portfolio_pnl_pct")) or 0.0
            benchmark_total_pnl = self._as_float(benchmark_row.get("total_portfolio_pnl_pct")) or 0.0
            active_deployed = float(active_row.get("deployed_capital_weight") or 0.0)
            benchmark_deployed = float(benchmark_row.get("deployed_capital_weight") or 0.0)
            diff = active_total_pnl - benchmark_total_pnl
            diff_row = {"active_minus_benchmark_total_pnl_pct": diff}
            paired_rows.append(
                {
                    "timestamp": active_row["snapshot_at"],
                    "active_total_pnl_pct": round(active_total_pnl, 2),
                    "benchmark_total_pnl_pct": round(benchmark_total_pnl, 2),
                    "active_minus_benchmark_total_pnl_pct": round(diff, 2),
                    "rolling_5_snapshot_avg_diff_pct": self._rolling_average(
                        paired_rows + [diff_row],
                        5,
                    ),
                    "rolling_10_snapshot_avg_diff_pct": self._rolling_average(
                        paired_rows + [diff_row],
                        10,
                    ),
                    "active_deployed_capital_weight": round(active_deployed, 4),
                    "benchmark_deployed_capital_weight": round(benchmark_deployed, 4),
                    "active_pnl_per_deployed_capital": self._pnl_per_deployed(active_total_pnl, active_deployed),
                    "benchmark_pnl_per_deployed_capital": self._pnl_per_deployed(benchmark_total_pnl, benchmark_deployed),
                }
            )
        return paired_rows

    def _comparison_summary(self, comparison_snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        if not comparison_snapshots:
            return {
                "latest_active_minus_benchmark_total_pnl_pct": None,
                "rolling_5_snapshot_avg_diff_pct": None,
                "rolling_10_snapshot_avg_diff_pct": None,
                "active_pnl_per_deployed_capital": None,
                "benchmark_pnl_per_deployed_capital": None,
                "snapshots_count": 0,
            }
        latest = comparison_snapshots[-1]
        return {
            "latest_active_minus_benchmark_total_pnl_pct": latest.get("active_minus_benchmark_total_pnl_pct"),
            "rolling_5_snapshot_avg_diff_pct": latest.get("rolling_5_snapshot_avg_diff_pct"),
            "rolling_10_snapshot_avg_diff_pct": latest.get("rolling_10_snapshot_avg_diff_pct"),
            "active_pnl_per_deployed_capital": latest.get("active_pnl_per_deployed_capital"),
            "benchmark_pnl_per_deployed_capital": latest.get("benchmark_pnl_per_deployed_capital"),
            "snapshots_count": len(comparison_snapshots),
        }

    @staticmethod
    def _rolling_average(rows: list[dict[str, Any]], window: int) -> float | None:
        recent_values = [
            float(row.get("active_minus_benchmark_total_pnl_pct"))
            for row in rows[-window:]
            if row.get("active_minus_benchmark_total_pnl_pct") is not None
        ]
        if not recent_values:
            return None
        return round(mean(recent_values), 2)

    @staticmethod
    def _pnl_per_deployed(total_pnl_pct: float, deployed_capital_weight: float) -> float | None:
        if deployed_capital_weight <= 0:
            return None
        return round(total_pnl_pct / deployed_capital_weight, 2)

    @staticmethod
    def _max_drawdown_pct(values: list[float | None]) -> float | None:
        cleaned = [float(value) for value in values if value is not None]
        if not cleaned:
            return None
        running_peak = cleaned[0]
        max_drawdown = 0.0
        for value in cleaned:
            running_peak = max(running_peak, value)
            max_drawdown = min(max_drawdown, value - running_peak)
        return round(abs(max_drawdown), 2)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


__all__ = ["PortfolioHistoryService"]
