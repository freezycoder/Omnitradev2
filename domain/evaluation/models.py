from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


OUTCOME_STATUS_OPEN = "open"
OUTCOME_STATUS_TARGET = "hit_target"
OUTCOME_STATUS_STOP = "hit_stop"
OUTCOME_STATUS_EXPIRED = "expired"

RESOLVED_OUTCOME_STATUSES = {
    OUTCOME_STATUS_TARGET,
    OUTCOME_STATUS_STOP,
    OUTCOME_STATUS_EXPIRED,
}


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    signal_id: str
    evaluated_at: str
    status: str
    resolution_reason: str
    evaluation_window_bars: int | None
    evaluation_window_days: int | None
    entry_price: float | None
    exit_price: float | None
    target_price: float | None
    stop_loss_price: float | None
    max_favorable_excursion_pct: float | None
    max_adverse_excursion_pct: float | None
    realized_return_pct: float | None
    holding_days: float | None
    first_target_hit_at: str | None
    first_stop_hit_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> "OutcomeRecord":
        return cls(
            outcome_id=row["outcome_id"],
            signal_id=row["signal_id"],
            evaluated_at=row["evaluated_at"],
            status=row["status"],
            resolution_reason=row["resolution_reason"],
            evaluation_window_bars=int(row["evaluation_window_bars"]) if row["evaluation_window_bars"] is not None else None,
            evaluation_window_days=int(row["evaluation_window_days"]) if row["evaluation_window_days"] is not None else None,
            entry_price=float(row["entry_price"]) if row["entry_price"] is not None else None,
            exit_price=float(row["exit_price"]) if row["exit_price"] is not None else None,
            target_price=float(row["target_price"]) if row["target_price"] is not None else None,
            stop_loss_price=float(row["stop_loss_price"]) if row["stop_loss_price"] is not None else None,
            max_favorable_excursion_pct=float(row["max_favorable_excursion_pct"]) if row["max_favorable_excursion_pct"] is not None else None,
            max_adverse_excursion_pct=float(row["max_adverse_excursion_pct"]) if row["max_adverse_excursion_pct"] is not None else None,
            realized_return_pct=float(row["realized_return_pct"]) if row["realized_return_pct"] is not None else None,
            holding_days=float(row["holding_days"]) if row["holding_days"] is not None else None,
            first_target_hit_at=row["first_target_hit_at"],
            first_stop_hit_at=row["first_stop_hit_at"],
        )

    def to_db_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PerformanceSummary:
    strategy_family: str
    total_signals: int
    resolved_signals: int
    total_resolved: int
    open_signals: int
    target_hits: int
    stop_hits: int
    expired_signals: int
    wins: int
    losses: int
    flats: int
    win_rate: float | None
    loss_rate: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    avg_return_pct: float | None
    median_return_pct: float | None
    expectancy_pct: float | None
    gross_expectancy_pct: float | None
    estimated_transaction_cost_pct: float
    net_expectancy_pct: float | None
    net_expectancy_modeled: bool
    reporting_basis: str
    risk_adjusted_view: float | None
    std_return_pct: float | None
    max_loss_pct: float | None
    max_drawdown_pct: float | None
    max_consecutive_losses: int
    risk_penalty: float | None
    risk_flag: str | None


__all__ = [
    "OUTCOME_STATUS_EXPIRED",
    "OUTCOME_STATUS_OPEN",
    "OUTCOME_STATUS_STOP",
    "OUTCOME_STATUS_TARGET",
    "OutcomeRecord",
    "PerformanceSummary",
    "RESOLVED_OUTCOME_STATUSES",
]
