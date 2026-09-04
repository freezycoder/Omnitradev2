from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from config.performance import PERFORMANCE_DB_FILE, PERFORMANCE_MODEL_VERSION, SUPPORTED_SIGNAL_STRATEGIES
from domain.evaluation.models import RESOLVED_OUTCOME_STATUSES, OutcomeRecord
from domain.signals.models import SignalRecord, build_dedupe_key, normalize_timestamp
from storage.sqlite import bootstrap_database, connection_scope


class DuplicatePerformanceEntryError(ValueError):
    pass


class ManualPerformanceLogService:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        bootstrap_database(self._db_path)

    def log_completed_trade(
        self,
        *,
        ticker: str,
        strategy_family: str,
        opened_on: date,
        closed_on: date,
        score: float,
        entry_price: float,
        exit_price: float,
        status: str,
    ) -> dict[str, Any]:
        normalized_ticker = ticker.upper().strip()
        if not normalized_ticker:
            raise ValueError("Ticker is required.")
        if strategy_family not in SUPPORTED_SIGNAL_STRATEGIES:
            raise ValueError(f"Unsupported strategy family: {strategy_family}.")
        if status not in RESOLVED_OUTCOME_STATUSES:
            raise ValueError(f"Unsupported outcome status: {status}.")
        if not 0 <= score <= 100:
            raise ValueError("Score must be between 0 and 100.")
        if entry_price <= 0 or exit_price <= 0:
            raise ValueError("Entry and exit prices must be greater than zero.")
        if closed_on < opened_on:
            raise ValueError("Closed date cannot be before opened date.")

        opened_at = datetime.combine(opened_on, datetime.min.time(), tzinfo=UTC)
        evaluated_at = datetime.combine(closed_on, datetime.min.time(), tzinfo=UTC)
        realized_return_pct = ((exit_price - entry_price) / entry_price) * 100
        holding_days = float((closed_on - opened_on).days)
        signal_id = uuid4().hex

        signal = SignalRecord(
            signal_id=signal_id,
            dedupe_key=build_dedupe_key(
                ticker=normalized_ticker,
                strategy_family=strategy_family,
                source_quality="manual",
                signal_origin="web_manual",
                created_at=opened_at,
                trade_state="MANUAL",
                recommendation_label="Manual log",
                entry_price=entry_price,
                model_version=PERFORMANCE_MODEL_VERSION,
            ),
            created_at=normalize_timestamp(opened_at),
            ticker=normalized_ticker,
            company_name=normalized_ticker,
            strategy_family=strategy_family,
            signal_origin="web_manual",
            source_quality="manual",
            model_version=PERFORMANCE_MODEL_VERSION,
            recommendation_label="Manual log",
            recommendation_confidence="Manual",
            trade_state="MANUAL",
            holding_period_label=f"{holding_days:g} days",
            score=float(score),
            entry_price=float(entry_price),
            target_price=float(exit_price) if status == "hit_target" else None,
            stop_loss_price=float(exit_price) if status == "hit_stop" else None,
            trend_direction=None,
            setup_type="manual",
            invalidation_note=None,
            accounting_quality_score=None,
            shenanigan_risk_score=None,
            accounting_data_completeness_score=None,
            accounting_assessment_confidence=None,
            news_score=None,
            news_impact=None,
            feature_snapshot_json=json.dumps(
                {
                    "origin": "web_manual",
                    "opened_on": opened_on.isoformat(),
                    "closed_on": closed_on.isoformat(),
                    "status": status,
                },
                sort_keys=True,
            ),
            evaluated=1,
        )
        outcome = OutcomeRecord(
            outcome_id=uuid4().hex,
            signal_id=signal_id,
            evaluated_at=normalize_timestamp(evaluated_at),
            status=status,
            resolution_reason="manual_web_log",
            evaluation_window_bars=None,
            evaluation_window_days=int(holding_days),
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            target_price=signal.target_price,
            stop_loss_price=signal.stop_loss_price,
            max_favorable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            realized_return_pct=realized_return_pct,
            holding_days=holding_days,
            first_target_hit_at=normalize_timestamp(evaluated_at) if status == "hit_target" else None,
            first_stop_hit_at=normalize_timestamp(evaluated_at) if status == "hit_stop" else None,
        )

        signal_payload = signal.to_db_dict()
        outcome_payload = outcome.to_db_dict()
        signal_columns = ", ".join(signal_payload)
        signal_placeholders = ", ".join(f":{key}" for key in signal_payload)
        outcome_columns = ", ".join(outcome_payload)
        outcome_placeholders = ", ".join(f":{key}" for key in outcome_payload)

        with connection_scope(self._db_path) as connection:
            try:
                connection.execute(
                    f"INSERT INTO signals ({signal_columns}) VALUES ({signal_placeholders})",
                    signal_payload,
                )
                connection.execute(
                    f"INSERT INTO signal_outcomes ({outcome_columns}) VALUES ({outcome_placeholders})",
                    outcome_payload,
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicatePerformanceEntryError(
                    "This completed trade appears to have already been logged."
                ) from exc

        return {
            "signal_id": signal_id,
            "ticker": normalized_ticker,
            "strategy_family": strategy_family,
            "status": status,
            "realized_return_pct": round(realized_return_pct, 2),
            "holding_days": holding_days,
        }


__all__ = ["DuplicatePerformanceEntryError", "ManualPerformanceLogService"]
