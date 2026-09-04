from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from typing import Any, Callable

from config.performance import LONG_TERM_HORIZON_DAYS, PERFORMANCE_DB_FILE, SUPPORTED_LONG_TERM_STRATEGIES, sample_quality_label
from storage.repositories.outcome_repository import OutcomeRepository
from storage.sqlite import bootstrap_database, connection_scope


@dataclass(frozen=True)
class LongTermCohortStats:
    total_signals: int
    resolved_signals: int
    open_signals: int
    wins: int
    losses: int
    flats: int
    win_rate: float | None
    avg_return_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    expectancy_pct: float | None
    realized_pnl_pct: float | None
    std_return_pct: float | None
    max_loss_pct: float | None
    max_drawdown_pct: float | None
    max_consecutive_losses: int
    risk_penalty: float | None
    risk_flag: str | None
    sample_quality: str
    low_sample: bool

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class LongTermPerformanceService:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        bootstrap_database(self._db_path)

    def build_dashboard_payload(self) -> dict[str, Any]:
        rows = self._load_long_term_rows()
        return {
            "overall": self._stats(rows).to_dict(),
            "by_horizon": self._grouped_stats(rows, self._horizon_label),
            "by_score_bucket": self._grouped_stats(rows, lambda row: self._score_bucket(row["score"])),
            "by_recommendation": self._grouped_stats(rows, lambda row: str(row["recommendation_label"] or "Unknown")),
            "by_trend": self._grouped_stats(rows, lambda row: str(row["trend_direction"] or "Unknown")),
            "by_accounting_risk": self._grouped_stats(rows, lambda row: self._accounting_risk_band(row["shenanigan_risk_score"])),
            "recent_resolved": self._recent_resolved(rows),
            "open_signals": self._open_signals(rows),
            "horizon_definitions": [
                {
                    "strategy_family": strategy_family,
                    "label": self._horizon_label({"strategy_family": strategy_family}),
                    "days": LONG_TERM_HORIZON_DAYS[strategy_family],
                }
                for strategy_family in SUPPORTED_LONG_TERM_STRATEGIES
            ],
        }

    def _load_long_term_rows(self) -> list[sqlite3.Row]:
        placeholders = ", ".join("?" for _ in SUPPORTED_LONG_TERM_STRATEGIES)
        query = f"""
            SELECT
                s.signal_id,
                s.created_at,
                s.ticker,
                s.company_name,
                s.strategy_family,
                s.source_quality,
                s.recommendation_label,
                s.recommendation_confidence,
                s.holding_period_label,
                s.score,
                s.entry_price,
                s.trend_direction,
                s.accounting_quality_score,
                s.shenanigan_risk_score,
                s.accounting_data_completeness_score,
                s.accounting_assessment_confidence,
                s.news_score,
                s.news_impact,
                s.evaluated,
                o.evaluated_at,
                o.status,
                o.exit_price,
                o.realized_return_pct,
                o.max_favorable_excursion_pct,
                o.max_adverse_excursion_pct,
                o.holding_days
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.strategy_family IN ({placeholders})
            ORDER BY s.created_at DESC
        """
        with connection_scope(self._db_path) as connection:
            return connection.execute(query, SUPPORTED_LONG_TERM_STRATEGIES).fetchall()

    def _stats(self, rows: list[sqlite3.Row]) -> LongTermCohortStats:
        returns = [
            float(row["realized_return_pct"])
            for row in rows
            if row["realized_return_pct"] is not None and isfinite(float(row["realized_return_pct"]))
        ]
        resolved = len(returns)
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        flats = sum(1 for value in returns if value == 0)
        win_rate_ratio = wins / resolved if resolved else None
        loss_rate_ratio = losses / resolved if resolved else None
        avg_win_pct = (sum(value for value in returns if value > 0) / wins) if wins else None
        avg_loss_pct = abs(sum(value for value in returns if value < 0) / losses) if losses else None
        avg_return_pct = (sum(returns) / resolved) if resolved else None
        expectancy_pct = (
            ((win_rate_ratio or 0.0) * (avg_win_pct or 0.0)) - ((loss_rate_ratio or 0.0) * (avg_loss_pct or 0.0))
            if resolved
            else None
        )
        risk_metrics = OutcomeRepository._risk_metrics_from_returns(returns)
        open_signals = sum(1 for row in rows if row["realized_return_pct"] is None)
        return LongTermCohortStats(
            total_signals=len(rows),
            resolved_signals=resolved,
            open_signals=open_signals,
            wins=wins,
            losses=losses,
            flats=flats,
            win_rate=round(win_rate_ratio * 100, 1) if win_rate_ratio is not None else None,
            avg_return_pct=round(avg_return_pct, 2) if avg_return_pct is not None else None,
            avg_win_pct=round(avg_win_pct, 2) if avg_win_pct is not None else None,
            avg_loss_pct=round(avg_loss_pct, 2) if avg_loss_pct is not None else None,
            expectancy_pct=round(expectancy_pct, 2) if expectancy_pct is not None else None,
            realized_pnl_pct=round(sum(returns), 2) if returns else None,
            std_return_pct=risk_metrics.get("std_return_pct"),
            max_loss_pct=risk_metrics.get("max_loss_pct"),
            max_drawdown_pct=risk_metrics.get("max_drawdown_pct"),
            max_consecutive_losses=int(risk_metrics.get("max_consecutive_losses") or 0),
            risk_penalty=risk_metrics.get("risk_penalty"),
            risk_flag=str(risk_metrics.get("risk_flag") or "No data"),
            sample_quality=sample_quality_label(resolved),
            low_sample=resolved < 15,
        )

    def _grouped_stats(
        self,
        rows: list[sqlite3.Row],
        key_fn: Callable[[sqlite3.Row | dict[str, Any]], str],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            grouped[key_fn(row)].append(row)
        payload = [{"segment": key, **self._stats(group).to_dict()} for key, group in grouped.items()]
        return sorted(
            payload,
            key=lambda row: (
                row.get("resolved_signals") or 0,
                row.get("expectancy_pct") if row.get("expectancy_pct") is not None else -999,
                row.get("total_signals") or 0,
            ),
            reverse=True,
        )

    def _recent_resolved(self, rows: list[sqlite3.Row], limit: int = 25) -> list[dict[str, Any]]:
        resolved = [row for row in rows if row["realized_return_pct"] is not None]
        resolved.sort(key=lambda row: str(row["evaluated_at"] or ""), reverse=True)
        return [
            {
                "evaluated_at": row["evaluated_at"],
                "ticker": row["ticker"],
                "company": row["company_name"],
                "horizon": self._horizon_label(row),
                "recommendation": row["recommendation_label"],
                "score": round(float(row["score"]), 1) if row["score"] is not None else None,
                "entry_price": round(float(row["entry_price"]), 2) if row["entry_price"] is not None else None,
                "exit_price": round(float(row["exit_price"]), 2) if row["exit_price"] is not None else None,
                "return_pct": round(float(row["realized_return_pct"]), 2),
                "max_favorable_pct": round(float(row["max_favorable_excursion_pct"]), 2) if row["max_favorable_excursion_pct"] is not None else None,
                "max_adverse_pct": round(float(row["max_adverse_excursion_pct"]), 2) if row["max_adverse_excursion_pct"] is not None else None,
            }
            for row in resolved[:limit]
        ]

    def _open_signals(self, rows: list[sqlite3.Row], limit: int = 50) -> list[dict[str, Any]]:
        now = datetime.now(tz=UTC)
        open_rows = [row for row in rows if row["realized_return_pct"] is None]
        open_rows.sort(key=lambda row: str(row["created_at"] or ""), reverse=True)
        payload: list[dict[str, Any]] = []
        for row in open_rows[:limit]:
            created_at = self._parse_dt(str(row["created_at"]))
            horizon_days = LONG_TERM_HORIZON_DAYS.get(str(row["strategy_family"]), 0)
            age_days = (now - created_at).total_seconds() / 86400.0
            days_remaining = max(horizon_days - age_days, 0.0)
            payload.append(
                {
                    "created_at": row["created_at"],
                    "ticker": row["ticker"],
                    "company": row["company_name"],
                    "horizon": self._horizon_label(row),
                    "recommendation": row["recommendation_label"],
                    "score": round(float(row["score"]), 1) if row["score"] is not None else None,
                    "entry_price": round(float(row["entry_price"]), 2) if row["entry_price"] is not None else None,
                    "age_days": round(age_days, 1),
                    "days_to_maturity": round(days_remaining, 1),
                    "source": row["source_quality"],
                }
            )
        return payload

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _horizon_label(row: sqlite3.Row | dict[str, Any]) -> str:
        strategy_family = str(row["strategy_family"])
        return {
            "long_term_3m": "3M",
            "long_term_6m": "6M",
            "long_term_12m": "12M",
        }.get(strategy_family, strategy_family)

    @staticmethod
    def _score_bucket(score: Any) -> str:
        if score is None:
            return "Unknown"
        value = float(score)
        if value >= 85:
            return "85+"
        if value >= 80:
            return "80-84"
        if value >= 75:
            return "75-79"
        if value >= 70:
            return "70-74"
        if value >= 65:
            return "65-69"
        return "<65"

    @staticmethod
    def _accounting_risk_band(value: Any) -> str:
        if value is None:
            return "Unknown"
        risk = float(value)
        if risk >= 70:
            return "High Risk (70+)"
        if risk >= 50:
            return "Elevated Risk (50-69)"
        if risk >= 30:
            return "Moderate Risk (30-49)"
        return "Low Risk (0-29)"


__all__ = ["LongTermCohortStats", "LongTermPerformanceService"]
