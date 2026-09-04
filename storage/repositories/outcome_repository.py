from __future__ import annotations

import sqlite3
from math import isfinite
from statistics import pstdev
from pathlib import Path

from domain.evaluation.models import OutcomeRecord
from storage.sqlite import bootstrap_database, connection_scope


class OutcomeRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        # Schema bootstrap is centralised in app startup; see storage/sqlite.py.

    def ensure_schema(self) -> None:
        # Idempotent: real work runs only on the first call per db_path.
        bootstrap_database(self._db_path)

    def insert_outcome(self, outcome: OutcomeRecord) -> bool:
        payload = outcome.to_db_dict()
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(f":{key}" for key in payload)
        query = f"INSERT INTO signal_outcomes ({columns}) VALUES ({placeholders})"
        with connection_scope(self._db_path) as connection:
            try:
                connection.execute(query, payload)
            except sqlite3.IntegrityError:
                return False
        return True

    def get_by_signal_id(self, signal_id: str) -> OutcomeRecord | None:
        query = """
            SELECT *
            FROM signal_outcomes
            WHERE signal_id = ?
            ORDER BY evaluated_at DESC
            LIMIT 1
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (signal_id,)).fetchone()
        return OutcomeRecord.from_row(row) if row else None

    def get_by_outcome_id(self, outcome_id: str) -> OutcomeRecord | None:
        query = "SELECT * FROM signal_outcomes WHERE outcome_id = ? LIMIT 1"
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (outcome_id,)).fetchone()
        return OutcomeRecord.from_row(row) if row else None

    def list_outcomes(
        self,
        strategy_family: str | None = None,
        limit: int = 200,
        ticker: str | None = None,
    ) -> list[OutcomeRecord]:
        query = """
            SELECT o.*
            FROM signal_outcomes o
            JOIN signals s ON s.signal_id = o.signal_id
            WHERE 1 = 1
        """
        params: list[object] = []
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        if ticker:
            query += " AND s.ticker = ?"
            params.append(ticker.upper().strip())
        query += " ORDER BY o.evaluated_at DESC LIMIT ?"
        params.append(limit)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [OutcomeRecord.from_row(row) for row in rows]

    def list_open_signal_ids_without_outcomes(self, strategy_family: str | None = None, limit: int = 500) -> list[str]:
        query = """
            SELECT s.signal_id
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.evaluated = 0
              AND o.signal_id IS NULL
        """
        params: list[object] = []
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        query += " ORDER BY s.created_at ASC LIMIT ?"
        params.append(limit)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [str(row["signal_id"]) for row in rows]

    def get_overall_resolved_stats(
        self,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> dict[str, float | int | None]:
        rows = self._load_resolved_rows(strategy_family=strategy_family, min_score=min_score)
        return self._rows_to_expectancy_stats(rows)

    def get_resolved_stats_by_strategy(
        self,
        min_score: int | None = None,
    ) -> list[dict[str, float | int | str | None]]:
        rows = self._load_resolved_rows(min_score=min_score)
        strategy_rows: list[dict[str, float | int | str | None]] = []
        for strategy_family in ("short_term_day", "short_term_swing"):
            scoped_rows = [row for row in rows if row["strategy_family"] == strategy_family]
            strategy_rows.append(
                {"strategy_family": strategy_family, **self._rows_to_expectancy_stats(scoped_rows)}
            )
        return strategy_rows

    def get_resolved_stats_by_score_bucket(
        self,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> list[dict[str, float | int | str | None]]:
        rows = self._load_resolved_rows(strategy_family=strategy_family, min_score=min_score)
        ordered_buckets = ("80+", "70-79", "60-69", "50-59", "<50")
        bucket_rows: list[dict[str, float | int | str | None]] = []
        for bucket in ordered_buckets:
            scoped_rows = [row for row in rows if self._score_bucket(float(row["score"])) == bucket]
            if not scoped_rows:
                continue
            bucket_rows.append({"score_bucket": bucket, **self._rows_to_expectancy_stats(scoped_rows)})
        return bucket_rows

    def get_resolved_stats_by_confidence_band(
        self,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> list[dict[str, float | int | str | None]]:
        rows = self._load_resolved_rows(strategy_family=strategy_family, min_score=min_score)
        confidence_bands = sorted({str(row["recommendation_confidence"] or "Unknown") for row in rows})
        return [
            {
                "confidence_band": band,
                **self._rows_to_expectancy_stats(
                    [row for row in rows if str(row["recommendation_confidence"] or "Unknown") == band]
                ),
            }
            for band in confidence_bands
        ]

    def get_resolved_stats_by_accounting_risk_band(
        self,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> list[dict[str, float | int | str | None]]:
        rows = self._load_resolved_rows(strategy_family=strategy_family, min_score=min_score)
        ordered_bands = (
            "Low Risk (0-29)",
            "Moderate Risk (30-49)",
            "Elevated Risk (50-69)",
            "High Risk (70+)",
            "Unknown",
        )
        payload: list[dict[str, float | int | str | None]] = []
        for band in ordered_bands:
            scoped_rows = [row for row in rows if self._accounting_risk_band(row["shenanigan_risk_score"]) == band]
            if not scoped_rows:
                continue
            payload.append({"accounting_risk_band": band, **self._rows_to_expectancy_stats(scoped_rows)})
        return payload

    def list_calibration_observations(self) -> list[sqlite3.Row]:
        """Return the resolved signal fields needed for research-only calibration."""
        query = """
            SELECT
                s.signal_id,
                s.ticker,
                s.strategy_family,
                s.score,
                s.recommendation_label,
                s.recommendation_confidence,
                s.setup_type,
                s.feature_snapshot_json,
                s.source_quality,
                s.created_at,
                o.realized_return_pct,
                o.evaluated_at
            FROM signal_outcomes o
            JOIN signals s ON s.signal_id = o.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
              AND o.realized_return_pct IS NOT NULL
            ORDER BY s.created_at ASC, o.evaluated_at ASC, s.ticker ASC
        """
        with connection_scope(self._db_path) as connection:
            return connection.execute(query).fetchall()

    def get_resolved_stats_by_edge_segment(
        self,
        strategy_family: str | None = None,
        min_resolved: int = 15,
    ) -> list[dict[str, float | int | str | dict | None]]:
        rows = self._load_resolved_rows(strategy_family=strategy_family, min_score=60)
        grouped_rows: dict[tuple[str, str, str, str, str], list[sqlite3.Row]] = {}
        for row in rows:
            score_bucket = self._score_bucket(float(row["score"])) if row["score"] is not None else None
            if score_bucket not in {"80+", "70-79", "60-69"}:
                continue
            key = (
                score_bucket,
                str(row["trade_state"] or "Unknown"),
                str(row["recommendation_label"] or "Unknown"),
                str(row["trend_direction"] or "unknown"),
                str(row["source_quality"] or "unknown"),
            )
            grouped_rows.setdefault(key, []).append(row)

        payload: list[dict[str, float | int | str | dict | None]] = []
        for key, group in grouped_rows.items():
            if len(group) < min_resolved:
                continue
            metrics = self._rows_to_expectancy_stats(group)
            payload.append(
                {
                    "segment": {
                        "score_bucket": key[0],
                        "trade_state": key[1],
                        "recommendation_label": key[2],
                        "trend_direction": key[3],
                        "source_quality": key[4],
                    },
                    "resolved_signals": int(metrics["resolved_signals"] or 0),
                    "wins": int(metrics["wins"] or 0),
                    "losses": int(metrics["losses"] or 0),
                    "flats": int(metrics["flats"] or 0),
                    "win_rate": metrics["win_rate"],
                    "avg_return_pct": metrics["avg_return_pct"],
                    "avg_win_pct": metrics["avg_win_pct"],
                    "avg_loss_pct": metrics["avg_loss_pct"],
                    "expectancy_pct": metrics["expectancy_pct"],
                    "std_return_pct": metrics["std_return_pct"],
                    "max_loss_pct": metrics["max_loss_pct"],
                    "max_drawdown_pct": metrics["max_drawdown_pct"],
                    "max_consecutive_losses": metrics["max_consecutive_losses"],
                    "risk_penalty": metrics["risk_penalty"],
                    "risk_flag": metrics["risk_flag"],
                }
            )
        return payload

    @staticmethod
    def _score_bucket(score: float | None) -> str:
        if score is None:
            return "<50"
        if score >= 80:
            return "80+"
        if score >= 70:
            return "70-79"
        if score >= 60:
            return "60-69"
        if score >= 50:
            return "50-59"
        return "<50"

    @staticmethod
    def _accounting_risk_band(risk_score: float | None) -> str:
        if risk_score is None:
            return "Unknown"
        if risk_score >= 70:
            return "High Risk (70+)"
        if risk_score >= 50:
            return "Elevated Risk (50-69)"
        if risk_score >= 30:
            return "Moderate Risk (30-49)"
        return "Low Risk (0-29)"

    def _load_resolved_rows(
        self,
        *,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> list[sqlite3.Row]:
        query = """
            SELECT
                s.strategy_family,
                s.score,
                s.recommendation_confidence,
                s.shenanigan_risk_score,
                s.trade_state,
                s.recommendation_label,
                LOWER(COALESCE(NULLIF(TRIM(s.trend_direction), ''), 'unknown')) AS trend_direction,
                COALESCE(NULLIF(TRIM(s.source_quality), ''), 'unknown') AS source_quality,
                o.realized_return_pct,
                o.evaluated_at
            FROM signal_outcomes o
            JOIN signals s ON s.signal_id = o.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
              AND o.realized_return_pct IS NOT NULL
        """
        params: list[object] = []
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        if min_score is not None:
            query += " AND s.score >= ?"
            params.append(min_score)
        query += " ORDER BY o.evaluated_at ASC, s.created_at ASC"
        with connection_scope(self._db_path) as connection:
            return connection.execute(query, params).fetchall()

    @classmethod
    def _rows_to_expectancy_stats(cls, rows: list[sqlite3.Row]) -> dict[str, float | int | str | None]:
        returns = cls._finite_returns(
            [float(row["realized_return_pct"]) for row in rows if row["realized_return_pct"] is not None]
        )
        total_resolved = len(returns)
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        flats = sum(1 for value in returns if value == 0)
        avg_win_pct = (sum(value for value in returns if value > 0) / wins) if wins else None
        avg_loss_pct = abs(sum(value for value in returns if value < 0) / losses) if losses else None
        avg_return_pct = (sum(returns) / total_resolved) if total_resolved else None
        win_rate_ratio = (wins / total_resolved) if total_resolved else None
        loss_rate_ratio = (losses / total_resolved) if total_resolved else None
        win_component = (win_rate_ratio or 0.0) * (avg_win_pct or 0.0)
        loss_component = (loss_rate_ratio or 0.0) * (avg_loss_pct or 0.0)
        expectancy_pct = win_component - loss_component if total_resolved else None
        risk_adjusted_view = (
            expectancy_pct / avg_loss_pct
            if expectancy_pct is not None and avg_loss_pct not in (None, 0)
            else None
        )
        realized_pnl_pct = sum(returns) if total_resolved else None
        risk_metrics = cls._risk_metrics_from_returns(returns)

        return {
            "total_resolved": total_resolved,
            "resolved_signals": total_resolved,
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": round(win_rate_ratio * 100, 1) if win_rate_ratio is not None else None,
            "loss_rate": round(loss_rate_ratio * 100, 1) if loss_rate_ratio is not None else None,
            "avg_win_pct": round(avg_win_pct, 2) if avg_win_pct is not None else None,
            "avg_loss_pct": round(avg_loss_pct, 2) if avg_loss_pct is not None else None,
            "avg_return_pct": round(avg_return_pct, 2) if avg_return_pct is not None else None,
            "expectancy_pct": round(expectancy_pct, 2) if expectancy_pct is not None else None,
            "realized_pnl_pct": round(realized_pnl_pct, 2) if realized_pnl_pct is not None else None,
            "risk_adjusted_view": round(risk_adjusted_view, 2) if risk_adjusted_view is not None else None,
            **risk_metrics,
        }

    @classmethod
    def _risk_metrics_from_returns(cls, returns: list[float]) -> dict[str, float | int | str | None]:
        returns = cls._finite_returns(returns)
        if not returns:
            return {
                "std_return_pct": None,
                "max_loss_pct": None,
                "max_drawdown_pct": None,
                "max_consecutive_losses": 0,
                "risk_penalty": None,
                "risk_flag": "No data",
            }

        std_return_pct = pstdev(returns) if len(returns) > 1 else 0.0
        worst_return = min(returns)
        max_loss_pct = abs(worst_return) if worst_return < 0 else 0.0

        cumulative = 0.0
        peak = 0.0
        max_drawdown_pct = 0.0
        max_consecutive_losses = 0
        current_loss_streak = 0
        for value in returns:
            cumulative += value
            peak = max(peak, cumulative)
            max_drawdown_pct = max(max_drawdown_pct, peak - cumulative)
            if value < 0:
                current_loss_streak += 1
                max_consecutive_losses = max(max_consecutive_losses, current_loss_streak)
            else:
                current_loss_streak = 0

        risk_penalty, risk_flag = cls._risk_penalty_and_flag(
            std_return_pct=std_return_pct,
            max_loss_pct=max_loss_pct,
            max_drawdown_pct=max_drawdown_pct,
            max_consecutive_losses=max_consecutive_losses,
        )
        return {
            "std_return_pct": round(std_return_pct, 2),
            "max_loss_pct": round(max_loss_pct, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "max_consecutive_losses": max_consecutive_losses,
            "risk_penalty": risk_penalty,
            "risk_flag": risk_flag,
        }

    @staticmethod
    def _finite_returns(returns: list[float]) -> list[float]:
        return [float(value) for value in returns if isfinite(float(value))]

    @staticmethod
    def _risk_penalty_and_flag(
        *,
        std_return_pct: float,
        max_loss_pct: float,
        max_drawdown_pct: float,
        max_consecutive_losses: int,
    ) -> tuple[float, str]:
        penalty = 0.0
        if std_return_pct >= 1.5:
            penalty += 0.25
        elif std_return_pct >= 0.75:
            penalty += 0.10

        if max_loss_pct >= 2.0:
            penalty += 0.25
        elif max_loss_pct >= 1.0:
            penalty += 0.10

        if max_drawdown_pct >= 4.0:
            penalty += 0.30
        elif max_drawdown_pct >= 2.0:
            penalty += 0.15

        if max_consecutive_losses >= 5:
            penalty += 0.20
        elif max_consecutive_losses >= 3:
            penalty += 0.10

        penalty = round(min(penalty, 1.0), 2)
        if penalty >= 0.55:
            risk_flag = "Fragile"
        elif penalty >= 0.25:
            risk_flag = "Watch"
        else:
            risk_flag = "Stable"
        return penalty, risk_flag


__all__ = ["OutcomeRepository"]
