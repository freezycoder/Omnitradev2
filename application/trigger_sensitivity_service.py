from __future__ import annotations

from pathlib import Path
from statistics import mean
from typing import Any

from application.entry_trigger_lab_service import ENTRY_METHODS, EntryTriggerLabService
from application.portfolio_engine_service import PortfolioEngineService
from application.strategy_execution_service import StrategyExecutionService
from config.performance import PERFORMANCE_DB_FILE, STRATEGY_V1


class TriggerSensitivityService:
    RISK_ADJUSTED_EDGE_METRIC = "expectancy_pct * (1 - risk_penalty)"

    def __init__(
        self,
        strategy_execution_service: StrategyExecutionService | None = None,
        entry_trigger_lab_service: EntryTriggerLabService | None = None,
        portfolio_engine_service: PortfolioEngineService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._strategy_execution_service = strategy_execution_service or StrategyExecutionService(db_path=self._db_path)
        self._entry_trigger_lab_service = entry_trigger_lab_service or EntryTriggerLabService(db_path=self._db_path)
        self._portfolio_engine_service = portfolio_engine_service or PortfolioEngineService(
            strategy_execution_service=self._strategy_execution_service,
            db_path=self._db_path,
        )

    def build_trigger_sensitivity_payload(self) -> dict[str, Any]:
        execution_payload = self._strategy_execution_service.build_strategy_v1_execution_payload(limit=300)
        signal_rows = execution_payload.get("signals", [])
        historical_payload = self._entry_trigger_lab_service.build_entry_trigger_payload(
            None,
            min_score=STRATEGY_V1.min_score,
            trend_direction=STRATEGY_V1.trend_direction,
            trade_state=STRATEGY_V1.trade_state,
        )
        historical_by_method = {
            str(row.get("method_key")): row
            for row in historical_payload.get("methods", [])
            if str(row.get("method_type")) in {"immediate", "pullback"}
        }

        method_rows: list[dict[str, Any]] = []
        for definition in ENTRY_METHODS:
            if definition.method_type not in {"immediate", "pullback"}:
                continue
            history = historical_by_method.get(definition.key)
            if history is None:
                continue
            method_signal_rows = self._rows_for_method(signal_rows, history, definition)
            deduplicated_rows = self._strategy_execution_service._deduplicate_signal_rows_for_execution(method_signal_rows)
            eligible_rows = [
                row
                for row in deduplicated_rows
                if self._expectancy_for_eligibility(row) > 0
                and float(row.get("position_size") or 0.0) > 0
            ]
            triggered_rows = [
                row for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "triggered"
            ]
            waiting_rows = [
                row for row in eligible_rows if str(row.get("trigger_status") or "").lower() == "waiting"
            ]
            eligible_capital = self._deployable_capital(eligible_rows)
            triggered_capital = self._deployable_capital(triggered_rows)
            eligible_count = len(eligible_rows)
            method_rows.append(
                {
                    "method_key": definition.key,
                    "method_label": definition.label,
                    "method_type": definition.method_type,
                    "pullback_pct": definition.pullback_pct,
                    "eligible_signals": eligible_count,
                    "triggered_signals": len(triggered_rows),
                    "trigger_rate": round(len(triggered_rows) / max(eligible_count, 1), 4),
                    "wait_ratio": round(len(waiting_rows) / max(eligible_count, 1), 4),
                    "expectancy_pct": history.get("expectancy_pct"),
                    "std_return_pct": history.get("std_return_pct"),
                    "max_loss_pct": history.get("max_loss_pct"),
                    "max_drawdown_pct": history.get("max_drawdown_pct"),
                    "max_consecutive_losses": history.get("max_consecutive_losses"),
                    "risk_penalty": history.get("risk_penalty"),
                    "risk_flag": history.get("risk_flag"),
                    "average_edge_score": round(mean([float(row.get("edge_quality_score") or 0.0) for row in eligible_rows]), 2)
                    if eligible_rows
                    else None,
                    "potential_deployed_capital": round(triggered_capital, 4),
                    "capital_capture_ratio": round(
                        triggered_capital / max(eligible_capital, 1e-9), 4
                    )
                    if eligible_capital > 0
                    else 0.0,
                    "edge_capture_score": self._rounded_pct_metric(
                        self._as_float(history.get("expectancy_pct")),
                        len(triggered_rows) / max(eligible_count, 1),
                    ),
                    "deployment_adjusted_edge": self._rounded_pct_metric(
                        self._as_float(history.get("expectancy_pct")),
                        triggered_capital / max(eligible_capital, 1e-9) if eligible_capital > 0 else 0.0,
                    ),
                    "risk_adjusted_edge": self._rounded_pct_metric(
                        self._as_float(history.get("expectancy_pct")),
                        max(0.0, 1.0 - float(history.get("risk_penalty") or 0.0)),
                    ),
                }
            )

        method_rows.sort(
            key=lambda row: (
                float(row.get("expectancy_pct") or -9999.0),
                float(row.get("capital_capture_ratio") or -9999.0),
            ),
            reverse=True,
        )
        live_row = next(
            (
                row
                for row in method_rows
                if str(row.get("method_type")) == STRATEGY_V1.entry_method
                and float(row.get("pullback_pct") or 0.0) == float(STRATEGY_V1.pullback_pct or 0.0)
            ),
            None,
        )
        return {
            "methods": method_rows,
            "live_method": live_row,
            "best_method_by_expectancy": self._best_method(
                method_rows,
                primary_key="expectancy_pct",
            ),
            "best_method_by_deployment_adjusted_edge": self._best_method(
                method_rows,
                primary_key="deployment_adjusted_edge",
            ),
            "best_method_by_risk_adjusted_edge": self._best_method(
                method_rows,
                primary_key="risk_adjusted_edge",
            ),
            "risk_adjusted_edge_formula": self.RISK_ADJUSTED_EDGE_METRIC,
        }

    def _rows_for_method(
        self,
        signal_rows: list[dict[str, Any]],
        history: dict[str, Any],
        definition: Any,
    ) -> list[dict[str, Any]]:
        method_rows: list[dict[str, Any]] = []
        for source_row in signal_rows:
            current_price = self._as_float(source_row.get("current_price"))
            signal_entry = self._as_float(source_row.get("signal_entry_price"))
            if current_price is None or signal_entry in (None, 0):
                continue

            row = dict(source_row)
            row["historical_cohort_expectancy_pct"] = history.get("expectancy_pct")
            row["historical_cohort_win_rate"] = history.get("win_rate")
            row["historical_cohort_resolved_signals"] = history.get("resolved_signals")
            row["historical_cohort_sample_quality"] = history.get("sample_quality")
            row["historical_cohort_risk_penalty"] = history.get("risk_penalty")
            row["historical_cohort_risk_flag"] = history.get("risk_flag")
            estimated_cost_pct = self._strategy_execution_service._estimated_transaction_cost_pct()
            row["estimated_transaction_cost_pct"] = round(estimated_cost_pct, 4)
            row["net_historical_expectancy_pct"] = (
                round(float(history.get("expectancy_pct")) - estimated_cost_pct, 4)
                if history.get("expectancy_pct") is not None
                else None
            )

            if definition.method_type == "immediate":
                row["trigger_price"] = signal_entry
                row["distance_to_trigger_pct"] = 0.0
                row["trigger_status"] = "triggered"
            else:
                trigger_price = signal_entry * (1 - float(definition.pullback_pct or 0.0) / 100.0)
                row["trigger_price"] = round(trigger_price, 2)
                row["distance_to_trigger_pct"] = round(((current_price - trigger_price) / trigger_price) * 100.0, 2)
                row["trigger_status"] = "triggered" if current_price <= trigger_price else "waiting"

            row.update(self._strategy_execution_service._time_stop_diagnostic(row))
            row["edge_quality_score"] = self._strategy_execution_service._edge_quality_score(row)
            row["expectancy_conflict_flag"] = self._strategy_execution_service._expectancy_conflict_flag(row)
            row.update(self._strategy_execution_service._execution_decision(row))
            position_size, sizing_reason = self._strategy_execution_service._position_size_and_reason(row)
            row["position_size"] = position_size
            row["sizing_reason"] = sizing_reason
            row["raw_weight"] = self._strategy_execution_service._raw_weight(row)
            method_rows.append(row)
        return method_rows

    def _deployable_capital(self, rows: list[dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        holdings = [self._portfolio_engine_service._holding_from_signal(row) for row in rows]
        eligible_holdings = [row for row in holdings if float(row.get("raw_weight") or 0.0) > 0]
        capped_holdings = self._portfolio_engine_service._normalize_and_cap(
            eligible_holdings,
            cap=self._portfolio_engine_service.MAX_SINGLE_NAME_WEIGHT,
        )
        return sum(float(row.get("final_weight") or 0.0) for row in capped_holdings)

    @staticmethod
    def _expectancy_for_eligibility(row: dict[str, Any]) -> float:
        net_expectancy = row.get("net_historical_expectancy_pct")
        if net_expectancy is not None:
            return float(net_expectancy)
        return float(row.get("historical_cohort_expectancy_pct") or 0.0)

    @staticmethod
    def _best_method(rows: list[dict[str, Any]], *, primary_key: str) -> dict[str, Any] | None:
        if not rows:
            return None
        return max(
            rows,
            key=lambda row: (
                float(row.get(primary_key) or float("-inf")),
                float(row.get("expectancy_pct") or float("-inf")),
                float(row.get("capital_capture_ratio") or float("-inf")),
                float(row.get("trigger_rate") or float("-inf")),
            ),
        )

    @staticmethod
    def _rounded_pct_metric(lhs: float | None, rhs: float | None) -> float | None:
        if lhs is None or rhs is None:
            return None
        return round(float(lhs) * float(rhs), 2)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


__all__ = ["TriggerSensitivityService"]
