from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from config.performance import RESEARCH_EXECUTION_LOG_FILE, RESEARCH_LOGGING_ENABLED


class ResearchLogService:
    def __init__(
        self,
        *,
        enabled: bool = RESEARCH_LOGGING_ENABLED,
        execution_log_file=RESEARCH_EXECUTION_LOG_FILE,
    ) -> None:
        self._enabled = enabled
        self._execution_log_file = execution_log_file

    def log_execution_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        preset: dict[str, Any],
        thresholds: dict[str, Any],
    ) -> None:
        if not self._enabled or not rows:
            return

        self._execution_log_file.parent.mkdir(parents=True, exist_ok=True)
        run_id = uuid4().hex
        logged_at = datetime.now(tz=UTC).isoformat()
        with self._execution_log_file.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        self._build_execution_record(
                            row,
                            preset=preset,
                            thresholds=thresholds,
                            run_id=run_id,
                            logged_at=logged_at,
                        ),
                        sort_keys=True,
                    )
                    + "\n"
                )

    @staticmethod
    def _build_execution_record(
        row: dict[str, Any],
        *,
        preset: dict[str, Any],
        thresholds: dict[str, Any],
        run_id: str,
        logged_at: str,
    ) -> dict[str, Any]:
        return {
            "logged_at": logged_at,
            "run_id": run_id,
            "decision": row.get("execution_decision"),
            "rejection_reason": row.get("execution_rejection_reason"),
            "ticker": row.get("ticker"),
            "signal_id": row.get("signal_id"),
            "created_at": row.get("created_at"),
            "regime": row.get("regime_label"),
            "horizon": row.get("holding_period_label"),
            "strategy_family": row.get("strategy_family"),
            "trade_state": row.get("trade_state"),
            "recommendation_label": row.get("recommendation_label"),
            "short_term_score": row.get("short_term_score"),
            "long_term_score": row.get("long_term_score"),
            "score": row.get("score"),
            "historical_expectancy_pct": row.get("historical_cohort_expectancy_pct"),
            "net_expectancy_pct": row.get("net_historical_expectancy_pct"),
            "edge_quality_score": row.get("edge_quality_score"),
            "estimated_transaction_cost_pct": row.get("estimated_transaction_cost_pct"),
            "reward_risk_ratio": row.get("reward_risk_ratio"),
            "turnover_annualized_signals": row.get("turnover_annualized_signals"),
            "trigger_status": row.get("trigger_status"),
            "trigger_price": row.get("trigger_price"),
            "current_price": row.get("current_price"),
            "thresholds": thresholds,
            "preset": preset,
        }


__all__ = ["ResearchLogService"]
