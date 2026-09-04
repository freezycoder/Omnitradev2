from __future__ import annotations

from pathlib import Path
from typing import Any

from application.portfolio_engine_service import PortfolioEngineService
from config.performance import PERFORMANCE_DB_FILE
from storage.repositories.outcome_repository import OutcomeRepository


class PortfolioPnlService:
    def __init__(
        self,
        portfolio_engine_service: PortfolioEngineService | None = None,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._portfolio_engine_service = portfolio_engine_service or PortfolioEngineService(db_path=self._db_path)
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)

    def build_strategy_v1_portfolio_pnl_payload(
        self,
        *,
        pullback_pct_override: float | None = None,
        portfolio_label: str = "Strategy_v1 Weighted",
        is_shadow_benchmark: bool = False,
    ) -> dict[str, Any]:
        portfolio_payload = self._portfolio_engine_service.build_strategy_v1_portfolio_payload(
            pullback_pct_override=pullback_pct_override,
            rule_label=portfolio_label,
            is_shadow_benchmark=is_shadow_benchmark,
        )
        return self._build_portfolio_pnl_payload(portfolio_payload, portfolio_label=portfolio_label)

    def build_strategy_v1_benchmark_portfolio_pnl_payload(self) -> dict[str, Any]:
        portfolio_payload = self._portfolio_engine_service.build_strategy_v1_benchmark_portfolio_payload()
        return self._build_portfolio_pnl_payload(
            portfolio_payload,
            portfolio_label="Conservative Benchmark Weighted",
        )

    def _build_portfolio_pnl_payload(self, portfolio_payload: dict[str, Any], *, portfolio_label: str) -> dict[str, Any]:
        holdings = portfolio_payload.get("holdings", [])
        holding_performance = [self._holding_performance(holding) for holding in holdings]

        actual_summary = self._portfolio_summary(holding_performance, weight_key="final_weight", return_key="holding_return_pct")
        equal_weight_summary = self._equal_weight_summary(holding_performance)
        immediate_baseline_summary = self._portfolio_summary(
            holding_performance,
            weight_key="final_weight",
            return_key="immediate_entry_return_pct",
        )

        return {
            "holdings": holding_performance,
            "summary": {
                **actual_summary,
                "cash_reserve_weight": round(float(portfolio_payload.get("summary", {}).get("cash_reserve_weight") or 0.0), 4),
                "holdings_count": len(holding_performance),
            },
            "baseline_comparison": [
                self._baseline_row(portfolio_label, actual_summary, versus_total=None),
                self._baseline_row(
                    "Equal Weight Baseline",
                    equal_weight_summary,
                    versus_total=self._difference(actual_summary.get("total_portfolio_pnl_pct"), equal_weight_summary.get("total_portfolio_pnl_pct")),
                ),
                self._baseline_row(
                    "Immediate Entry Baseline",
                    immediate_baseline_summary,
                    versus_total=self._difference(actual_summary.get("total_portfolio_pnl_pct"), immediate_baseline_summary.get("total_portfolio_pnl_pct")),
                ),
            ],
        }

    def _holding_performance(self, holding: dict[str, Any]) -> dict[str, Any]:
        signal_id = str(holding.get("signal_id") or "")
        outcome = self._outcome_repository.get_by_signal_id(signal_id) if signal_id else None
        exit_price = outcome.exit_price if outcome and outcome.exit_price is not None else None
        is_resolved = bool(outcome and outcome.exit_price is not None)
        status = "Resolved" if is_resolved else "Open"
        mark_price = exit_price if is_resolved else holding.get("current_price")
        entry_price = self._as_float(holding.get("entry_price"))
        immediate_entry_price = self._as_float(holding.get("immediate_entry_price"))
        current_price = self._as_float(holding.get("current_price"))
        final_weight = self._as_float(holding.get("final_weight")) or 0.0

        holding_return_pct = self._return_pct(entry_price, self._as_float(mark_price))
        immediate_entry_return_pct = self._return_pct(immediate_entry_price, self._as_float(mark_price))
        weighted_return_contribution_pct = (
            round(final_weight * holding_return_pct, 4) if holding_return_pct is not None else None
        )
        weighted_immediate_baseline_contribution_pct = (
            round(final_weight * immediate_entry_return_pct, 4)
            if immediate_entry_return_pct is not None
            else None
        )

        return {
            **holding,
            "status": status,
            "entry_price": round(entry_price, 2) if entry_price is not None else None,
            "immediate_entry_price": round(immediate_entry_price, 2) if immediate_entry_price is not None else None,
            "current_price": round(current_price, 2) if current_price is not None else None,
            "exit_price": round(float(exit_price), 2) if exit_price is not None else None,
            "holding_return_pct": round(holding_return_pct, 2) if holding_return_pct is not None else None,
            "immediate_entry_return_pct": (
                round(immediate_entry_return_pct, 2) if immediate_entry_return_pct is not None else None
            ),
            "weighted_return_contribution_pct": weighted_return_contribution_pct,
            "weighted_immediate_baseline_contribution_pct": weighted_immediate_baseline_contribution_pct,
        }

    def _portfolio_summary(
        self,
        holdings: list[dict[str, Any]],
        *,
        weight_key: str,
        return_key: str,
    ) -> dict[str, Any]:
        deployed_capital_weight = round(sum(self._as_float(row.get(weight_key)) or 0.0 for row in holdings), 4)
        open_holdings = 0
        resolved_holdings = 0
        realized_pnl_pct = 0.0
        unrealized_pnl_pct = 0.0
        resolved_weight = 0.0
        winning_resolved_weight = 0.0

        for row in holdings:
            weight = self._as_float(row.get(weight_key)) or 0.0
            holding_return = self._as_float(row.get(return_key))
            status = str(row.get("status") or "Open")
            if status == "Resolved":
                resolved_holdings += 1
                if holding_return is not None:
                    realized_pnl_pct += weight * holding_return
                    resolved_weight += weight
                    if holding_return > 0:
                        winning_resolved_weight += weight
            else:
                open_holdings += 1
                if holding_return is not None:
                    unrealized_pnl_pct += weight * holding_return

        weighted_hit_rate = (
            round((winning_resolved_weight / resolved_weight) * 100.0, 1) if resolved_weight > 0 else None
        )
        total_portfolio_pnl_pct = realized_pnl_pct + unrealized_pnl_pct
        return {
            "deployed_capital_weight": deployed_capital_weight,
            "realized_pnl_pct": round(realized_pnl_pct, 2),
            "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            "total_portfolio_pnl_pct": round(total_portfolio_pnl_pct, 2),
            "weighted_hit_rate": weighted_hit_rate,
            "open_holdings": open_holdings,
            "resolved_holdings": resolved_holdings,
        }

    def _equal_weight_summary(self, holdings: list[dict[str, Any]]) -> dict[str, Any]:
        if not holdings:
            return self._portfolio_summary([], weight_key="equal_weight", return_key="holding_return_pct")

        deployed_capital_weight = sum(self._as_float(row.get("final_weight")) or 0.0 for row in holdings)
        equal_weight = deployed_capital_weight / len(holdings) if holdings else 0.0
        equal_weight_holdings = [{**row, "equal_weight": equal_weight} for row in holdings]
        return self._portfolio_summary(equal_weight_holdings, weight_key="equal_weight", return_key="holding_return_pct")

    @staticmethod
    def _baseline_row(name: str, summary: dict[str, Any], *, versus_total: float | None) -> dict[str, Any]:
        return {
            "Baseline": name,
            "Deployed": summary.get("deployed_capital_weight"),
            "Realized PnL": summary.get("realized_pnl_pct"),
            "Unrealized PnL": summary.get("unrealized_pnl_pct"),
            "Total PnL": summary.get("total_portfolio_pnl_pct"),
            "Weighted Hit Rate": summary.get("weighted_hit_rate"),
            "Open Holdings": summary.get("open_holdings"),
            "Resolved Holdings": summary.get("resolved_holdings"),
            "Vs Strategy_v1": round(versus_total, 2) if versus_total is not None else None,
        }

    @staticmethod
    def _return_pct(entry_price: float | None, mark_price: float | None) -> float | None:
        if entry_price in (None, 0) or mark_price is None:
            return None
        return ((mark_price - entry_price) / entry_price) * 100.0

    @staticmethod
    def _difference(lhs: float | None, rhs: float | None) -> float | None:
        if lhs is None or rhs is None:
            return None
        return lhs - rhs

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)


__all__ = ["PortfolioPnlService"]
