from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from config.performance import SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT, SIGNAL_DEDUPE_LOOKBACK_DAYS
from domain.signals.models import SignalRecord, parse_timestamp
from storage.sqlite import bootstrap_database, connection_scope


class SignalRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        # Schema is bootstrapped centrally at app startup. Avoid re-running DDL
        # on every repository construction — that fights connection pooling
        # and slows down hot paths like the per-ticker scan loop.

    def ensure_schema(self) -> None:
        # Idempotent: real work runs only on the first call per db_path.
        bootstrap_database(self._db_path)

    def insert_signal(self, signal: SignalRecord) -> bool:
        payload = signal.to_db_dict()
        columns = ", ".join(payload.keys())
        placeholders = ", ".join(f":{key}" for key in payload)
        query = f"INSERT INTO signals ({columns}) VALUES ({placeholders})"
        with connection_scope(self._db_path) as connection:
            try:
                connection.execute(query, payload)
            except sqlite3.IntegrityError:
                return False
        return True

    def get_by_signal_id(self, signal_id: str) -> SignalRecord | None:
        query = "SELECT * FROM signals WHERE signal_id = ? LIMIT 1"
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (signal_id,)).fetchone()
        return SignalRecord.from_row(row) if row else None

    def get_by_dedupe_key(self, dedupe_key: str) -> SignalRecord | None:
        query = "SELECT * FROM signals WHERE dedupe_key = ? LIMIT 1"
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (dedupe_key,)).fetchone()
        return SignalRecord.from_row(row) if row else None

    def exists_by_dedupe_key(self, dedupe_key: str) -> bool:
        query = "SELECT 1 FROM signals WHERE dedupe_key = ? LIMIT 1"
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, (dedupe_key,)).fetchone()
        return row is not None

    def list_open_signals(self, strategy_family: str | None = None, limit: int = 500) -> list[SignalRecord]:
        query = """
            SELECT *
            FROM signals
            WHERE evaluated = 0
        """
        params: list[object] = []
        if strategy_family:
            query += " AND strategy_family = ?"
            params.append(strategy_family)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [SignalRecord.from_row(row) for row in rows]

    def list_open_execution_candidates(
        self,
        *,
        trade_state: str,
        min_score: int,
        strategy_families: tuple[str, ...],
        trend_direction: str | None = None,
        limit: int = 500,
    ) -> list[SignalRecord]:
        placeholders = ", ".join("?" for _ in strategy_families)
        query = f"""
            SELECT *
            FROM signals
            WHERE evaluated = 0
              AND trade_state = ?
              AND score >= ?
              AND strategy_family IN ({placeholders})
        """
        params: list[object] = [trade_state, min_score, *strategy_families]
        if trend_direction and trend_direction.lower() != "all":
            query += " AND LOWER(COALESCE(trend_direction, '')) = ?"
            params.append(trend_direction.lower())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [SignalRecord.from_row(row) for row in rows]

    def list_signals(
        self,
        limit: int = 100,
        strategy_family: str | None = None,
        source_quality: str | None = None,
        ticker: str | None = None,
    ) -> list[SignalRecord]:
        query = "SELECT * FROM signals WHERE 1 = 1"
        params: list[object] = []
        if strategy_family:
            query += " AND strategy_family = ?"
            params.append(strategy_family)
        if source_quality:
            query += " AND source_quality = ?"
            params.append(source_quality)
        if ticker:
            query += " AND ticker = ?"
            params.append(ticker.upper().strip())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [SignalRecord.from_row(row) for row in rows]

    def get_signal_counts(
        self,
        strategy_family: str | None = None,
        min_score: int | None = None,
    ) -> dict[str, int]:
        query = """
            SELECT
                COUNT(*) AS total_signals,
                SUM(CASE WHEN o.signal_id IS NOT NULL THEN 1 ELSE 0 END) AS resolved_signals,
                SUM(CASE WHEN o.signal_id IS NULL THEN 1 ELSE 0 END) AS open_signals
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE 1 = 1
        """
        params: list[object] = []
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        if min_score is not None:
            query += " AND s.score >= ?"
            params.append(min_score)
        with connection_scope(self._db_path) as connection:
            row = connection.execute(query, params).fetchone()
        return {
            "total_signals": int(row["total_signals"] or 0),
            "resolved_signals": int(row["resolved_signals"] or 0),
            "open_signals": int(row["open_signals"] or 0),
        }

    def mark_evaluated(self, signal_id: str) -> None:
        query = "UPDATE signals SET evaluated = 1 WHERE signal_id = ?"
        with connection_scope(self._db_path) as connection:
            connection.execute(query, (signal_id,))

    def find_recent_duplicate(self, candidate: SignalRecord) -> SignalRecord | None:
        created_at = candidate.created_at_datetime
        window_start = (created_at - timedelta(days=SIGNAL_DEDUPE_LOOKBACK_DAYS)).isoformat()
        window_end = (created_at + timedelta(days=SIGNAL_DEDUPE_LOOKBACK_DAYS)).isoformat()
        query = """
            SELECT *
            FROM signals
            WHERE ticker = ?
              AND strategy_family = ?
              AND signal_origin = ?
              AND source_quality = ?
              AND model_version = ?
              AND created_at BETWEEN ? AND ?
            ORDER BY created_at DESC
        """
        params = (
            candidate.ticker,
            candidate.strategy_family,
            candidate.signal_origin,
            candidate.source_quality,
            candidate.model_version,
            window_start,
            window_end,
        )
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        for row in rows:
            existing = SignalRecord.from_row(row)
            if self._is_duplicate(existing, candidate):
                return existing
        return None

    @staticmethod
    def _is_duplicate(existing: SignalRecord, candidate: SignalRecord) -> bool:
        if existing.trade_state != candidate.trade_state:
            return False
        if existing.recommendation_label != candidate.recommendation_label:
            return False
        if existing.source_quality != candidate.source_quality:
            return False
        if existing.created_at_date != candidate.created_at_date:
            return False

        existing_entry = existing.entry_price
        candidate_entry = candidate.entry_price
        if existing_entry is None or candidate_entry is None:
            return existing_entry == candidate_entry
        if existing_entry <= 0:
            return abs(candidate_entry - existing_entry) < 1e-9

        entry_change_pct = abs((candidate_entry - existing_entry) / existing_entry) * 100
        return entry_change_pct <= SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT


__all__ = ["SignalRepository"]
