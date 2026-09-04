from __future__ import annotations

from pathlib import Path
from typing import Any

from application.strategy_execution_service import StrategyExecutionService
from config.performance import PERFORMANCE_DB_FILE


class PortfolioEngineService:
    MAX_SINGLE_NAME_WEIGHT = 0.20
    FRAGILE_MULTIPLIER = 0.25

    def __init__(
        self,
        strategy_execution_service: StrategyExecutionService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._strategy_execution_service = strategy_execution_service or StrategyExecutionService(
            db_path=self._db_path,
        )

    def build_strategy_v1_portfolio_payload(
        self,
        *,
        pullback_pct_override: float | None = None,
        rule_label: str | None = None,
        is_shadow_benchmark: bool = False,
    ) -> dict[str, Any]:
        execution_payload = self._strategy_execution_service.build_strategy_v1_execution_payload(
            pullback_pct_override=pullback_pct_override,
            rule_label=rule_label,
            is_shadow_benchmark=is_shadow_benchmark,
        )
        return self._build_portfolio_payload_from_execution(execution_payload)

    def build_strategy_v1_benchmark_portfolio_payload(self) -> dict[str, Any]:
        return self.build_strategy_v1_portfolio_payload(
            pullback_pct_override=1.00,
            rule_label="Conservative Benchmark · Pullback 1.00%",
            is_shadow_benchmark=True,
        )

    def _build_portfolio_payload_from_execution(self, execution_payload: dict[str, Any]) -> dict[str, Any]:
        triggered_rows = execution_payload.get("ranked_triggered_signals", [])
        positive_expectancy_rows = [
            row for row in triggered_rows if self._expectancy_for_eligibility(row) > 0
        ]
        eligible_rows = [row for row in positive_expectancy_rows if self._is_eligible(row)]
        risk_adjusted_rows = [self._holding_from_signal(row) for row in eligible_rows]
        risk_eligible_rows = [row for row in risk_adjusted_rows if float(row.get("raw_weight") or 0.0) > 0]

        holdings = risk_eligible_rows
        capped_holdings = self._normalize_and_cap(holdings, cap=self.MAX_SINGLE_NAME_WEIGHT)

        weighted_expectancy = sum(
            float(holding["final_weight"]) * float(holding.get("historical_expectancy_pct") or 0.0)
            for holding in capped_holdings
        )
        weighted_net_expectancy = sum(
            float(holding["final_weight"]) * float(holding.get("net_expectancy_pct") or 0.0)
            for holding in capped_holdings
        )
        weighted_risk_penalty = sum(
            float(holding["final_weight"]) * float(holding.get("risk_penalty") or 0.0)
            for holding in capped_holdings
        )
        top_3_concentration = sum(
            holding["final_weight"]
            for holding in sorted(capped_holdings, key=lambda item: float(item["final_weight"]), reverse=True)[:3]
        )
        invested_weight = sum(float(holding["final_weight"]) for holding in capped_holdings)
        cash_reserve_weight = max(0.0, 1.0 - invested_weight)

        return {
            "preset": execution_payload.get("preset", {}),
            "total_triggered_signals": len(triggered_rows),
            "positive_expectancy_signals_count": len(positive_expectancy_rows),
            "eligible_signals_count": len(eligible_rows),
            "eligible_after_risk_filter_count": len(risk_eligible_rows),
            "holdings_count": len(capped_holdings),
            "holdings": capped_holdings,
            "summary": {
                "holdings_count": len(capped_holdings),
                "positive_expectancy_signals_count": len(positive_expectancy_rows),
                "eligible_signals_count": len(eligible_rows),
                "eligible_after_risk_filter_count": len(risk_eligible_rows),
                "total_triggered_signals": len(triggered_rows),
                "weighted_average_expectancy_pct": round(weighted_expectancy, 2) if capped_holdings else None,
                "weighted_average_net_expectancy_pct": round(weighted_net_expectancy, 2) if capped_holdings else None,
                "weighted_average_risk_penalty": round(weighted_risk_penalty, 2) if capped_holdings else None,
                "max_single_name_weight": max((holding["final_weight"] for holding in capped_holdings), default=0.0),
                "concentration_top_3_pct": round(top_3_concentration * 100.0, 1) if capped_holdings else 0.0,
                "cash_reserve_weight": round(cash_reserve_weight, 4),
                "cash_reserve_reason": self._cash_reserve_reason(
                    total_triggered=len(triggered_rows),
                    positive_expectancy=len(positive_expectancy_rows),
                    eligible=len(eligible_rows),
                    risk_eligible=len(risk_eligible_rows),
                    holdings_count=len(capped_holdings),
                    cash_reserve_weight=cash_reserve_weight,
                    cap=self.MAX_SINGLE_NAME_WEIGHT,
                ),
                "total_weight_check": round(invested_weight + cash_reserve_weight, 6),
            },
        }

    def _is_eligible(self, row: dict[str, Any]) -> bool:
        if str(row.get("execution_decision") or "") in {"rejected", "unavailable"}:
            return False
        expectancy = self._expectancy_for_eligibility(row)
        position_size = float(row.get("position_size") or 0.0)
        return expectancy > 0 and position_size > 0

    @staticmethod
    def _expectancy_for_eligibility(row: dict[str, Any]) -> float:
        net_expectancy = row.get("net_historical_expectancy_pct")
        if net_expectancy is not None:
            return float(net_expectancy)
        return float(row.get("historical_cohort_expectancy_pct") or 0.0)

    @staticmethod
    def _cash_reserve_reason(
        *,
        total_triggered: int,
        positive_expectancy: int,
        eligible: int,
        risk_eligible: int,
        holdings_count: int,
        cash_reserve_weight: float,
        cap: float,
    ) -> str:
        if cash_reserve_weight <= 0:
            return "Cash is low because the portfolio can fully deploy within the current single-name cap."
        if total_triggered == 0:
            return "Cash is high because no triggered signals are available for allocation."
        if positive_expectancy == 0:
            return "Cash is high because none of the triggered signals currently have positive expectancy."
        if eligible == 0:
            return "Cash is high because no triggered signals passed the positive-expectancy and positive-size eligibility rules."
        if risk_eligible == 0:
            return "Cash is high because the risk filter reduced all otherwise eligible triggered signals to zero raw weight."
        max_deployable = holdings_count * cap
        if max_deployable < 1.0:
            return (
                f"Cash is high because only {holdings_count} holding{'s' if holdings_count != 1 else ''} qualified. "
                f"With a {cap:.0%} single-name cap, the engine can deploy at most {max_deployable:.0%} and keeps the remainder in cash."
            )
        if risk_eligible < eligible:
            return "Cash remains elevated because the risk filter removed some otherwise eligible triggered signals before normalization."
        return "Cash remains because capped holdings could not absorb the full portfolio without breaking the single-name cap."

    def _holding_from_signal(self, row: dict[str, Any]) -> dict[str, Any]:
        risk_penalty = float(row.get("historical_cohort_risk_penalty") or 0.0)
        risk_flag = str(row.get("historical_cohort_risk_flag") or "No data")
        base_raw_weight = float(row.get("raw_weight") or 0.0)
        raw_weight = base_raw_weight
        reason_parts = [
            f"Net expectancy {self._expectancy_for_eligibility(row):+.2f}%",
            f"size {float(row.get('position_size') or 0.0):.2f}",
        ]

        if risk_flag == "Fragile":
            raw_weight = raw_weight * self.FRAGILE_MULTIPLIER
            reason_parts.append("fragile cohort haircut")
        elif risk_flag == "Watch":
            reason_parts.append("watch risk profile")
        else:
            reason_parts.append("stable cohort")

        return {
            "signal_id": row.get("signal_id"),
            "ticker": row.get("ticker"),
            "company": row.get("company_name"),
            "strategy": row.get("strategy_family"),
            "regime": row.get("regime_label"),
            "created_at": row.get("created_at"),
            "score": row.get("score"),
            "short_term_score": row.get("short_term_score"),
            "long_term_score": row.get("long_term_score"),
            "edge_score": row.get("edge_quality_score"),
            "position_size": row.get("position_size"),
            "risk_penalty": round(risk_penalty, 2),
            "turnover_penalty": row.get("turnover_penalty"),
            "raw_weight": round(raw_weight, 4),
            "final_weight": 0.0,
            "entry_price": row.get("trigger_price"),
            "immediate_entry_price": row.get("signal_entry_price"),
            "current_price": row.get("current_price"),
            "trigger_price": row.get("trigger_price"),
            "trigger_status": row.get("trigger_status"),
            "historical_expectancy_pct": row.get("historical_cohort_expectancy_pct"),
            "net_expectancy_pct": row.get("net_historical_expectancy_pct"),
            "estimated_transaction_cost_pct": row.get("estimated_transaction_cost_pct"),
            "historical_win_rate": row.get("historical_cohort_win_rate"),
            "reward_risk_ratio": row.get("reward_risk_ratio"),
            "time_stop_status": row.get("time_stop_status"),
            "execution_decision": row.get("execution_decision"),
            "execution_rejection_reason": row.get("execution_rejection_reason"),
            "allocation_reason": ", ".join(reason_parts),
            "risk_flag": risk_flag,
        }

    def _normalize_and_cap(self, holdings: list[dict[str, Any]], *, cap: float) -> list[dict[str, Any]]:
        if not holdings:
            return []

        total_raw = sum(float(holding["raw_weight"]) for holding in holdings)
        if total_raw <= 0:
            return []

        normalized = [dict(holding, final_weight=float(holding["raw_weight"]) / total_raw) for holding in holdings]
        adjusted = self._apply_cap(normalized, cap=cap)
        adjusted.sort(
            key=lambda holding: (
                float(holding["final_weight"]),
                float(holding.get("edge_score") or 0.0),
                str(holding.get("ticker") or ""),
            ),
            reverse=True,
        )
        target_total = min(1.0, round(sum(float(holding.get("final_weight") or 0.0) for holding in adjusted), 4))
        rounded_holdings = [
            {
                **holding,
                "raw_weight": round(float(holding["raw_weight"]), 4),
                "final_weight": round(float(holding["final_weight"]), 4),
            }
            for holding in adjusted
        ]
        return self._rebalance_rounded_weights(rounded_holdings, cap=cap, target_total=target_total)

    def _apply_cap(self, holdings: list[dict[str, Any]], *, cap: float) -> list[dict[str, Any]]:
        adjusted = [dict(holding) for holding in holdings]
        total_capacity = len(adjusted) * cap
        if total_capacity <= 1.0:
            for holding in adjusted:
                holding["final_weight"] = min(float(holding["final_weight"]), cap)
            return adjusted

        for _ in range(10):
            overweight = [holding for holding in adjusted if float(holding["final_weight"]) > cap + 1e-9]
            if not overweight:
                break

            excess = 0.0
            for holding in overweight:
                excess += float(holding["final_weight"]) - cap
                holding["final_weight"] = cap

            recipients = [holding for holding in adjusted if float(holding["final_weight"]) < cap - 1e-9]
            if not recipients or excess <= 0:
                break

            recipient_basis = sum(float(holding["raw_weight"]) for holding in recipients)
            if recipient_basis <= 0:
                equal_share = excess / len(recipients)
                for holding in recipients:
                    holding["final_weight"] = min(cap, float(holding["final_weight"]) + equal_share)
            else:
                for holding in recipients:
                    share = excess * (float(holding["raw_weight"]) / recipient_basis)
                    holding["final_weight"] = min(cap, float(holding["final_weight"]) + share)

            total = sum(float(holding["final_weight"]) for holding in adjusted)
            if total > 0:
                for holding in adjusted:
                    holding["final_weight"] = float(holding["final_weight"]) / total

        total = sum(float(holding["final_weight"]) for holding in adjusted)
        if total > 0:
            for holding in adjusted:
                holding["final_weight"] = float(holding["final_weight"]) / total
        return adjusted

    @staticmethod
    def _rebalance_rounded_weights(
        holdings: list[dict[str, Any]],
        *,
        cap: float,
        target_total: float,
    ) -> list[dict[str, Any]]:
        if not holdings:
            return holdings

        current_total = round(sum(float(holding.get("final_weight") or 0.0) for holding in holdings), 4)
        diff = round(target_total - current_total, 4)
        if abs(diff) < 0.0001:
            return holdings

        if diff < 0:
            remaining = abs(diff)
            for holding in sorted(holdings, key=lambda item: float(item.get("final_weight") or 0.0), reverse=True):
                weight = float(holding.get("final_weight") or 0.0)
                adjustment = min(weight, remaining)
                holding["final_weight"] = round(weight - adjustment, 4)
                remaining = round(remaining - adjustment, 4)
                if remaining <= 0:
                    break
            return holdings

        remaining = diff
        for holding in sorted(holdings, key=lambda item: float(item.get("raw_weight") or 0.0), reverse=True):
            weight = float(holding.get("final_weight") or 0.0)
            room = max(0.0, cap - weight)
            adjustment = min(room, remaining)
            if adjustment <= 0:
                continue
            holding["final_weight"] = round(weight + adjustment, 4)
            remaining = round(remaining - adjustment, 4)
            if remaining <= 0:
                break
        return holdings


__all__ = ["PortfolioEngineService"]
