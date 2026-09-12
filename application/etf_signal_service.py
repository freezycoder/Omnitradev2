from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pandas as pd

from config.performance import LOGGABLE_SOURCE_QUALITIES, LOGGABLE_TRADE_STATES, PERFORMANCE_MODEL_VERSION
from domain.assets import AssetType
from domain.recommendations.engine import build_short_term_recommendation
from domain.scoring.short_term import build_short_term_view
from domain.signals.models import SignalRecord, build_dedupe_key, normalize_timestamp
from domain.signals.trade_levels import validate_long_trade_levels
from storage.repositories.signal_repository import SignalRepository


class EtfSignalService:
    def __init__(self, signal_repository: SignalRepository | None = None) -> None:
        self._signal_repository = signal_repository or SignalRepository()

    def log_from_history(
        self,
        *,
        ticker: str,
        name: str | None,
        history: pd.DataFrame,
        omni_score: float | None,
        origin: str = "etf_screener",
        source_quality: str = "live",
    ) -> int:
        if source_quality not in LOGGABLE_SOURCE_QUALITIES or history is None or history.empty:
            return 0
        try:
            view = build_short_term_view(history)
            recommendation = build_short_term_recommendation(view)
        except Exception:
            return 0
        inserted = 0
        for strategy_family, setup in (
            ("short_term_day", view.day_trade),
            ("short_term_swing", view.swing_trade),
        ):
            if setup.trade_state_label not in LOGGABLE_TRADE_STATES:
                continue
            validation = validate_long_trade_levels(
                entry_price=setup.entry_price,
                target_price=setup.target_price,
                stop_loss_price=setup.stop_loss_price,
                reference_price=float(history["Close"].iloc[-1]) if "Close" in history.columns else None,
            )
            if not validation.valid:
                continue
            signal = self._build_signal(
                ticker=ticker,
                name=name,
                origin=origin,
                source_quality=source_quality,
                strategy_family=strategy_family,
                score=float(setup.score),
                trade_state=setup.trade_state_label,
                holding_period_label=setup.holding_period_label,
                entry_price=setup.entry_price,
                target_price=setup.target_price,
                stop_loss_price=setup.stop_loss_price,
                setup_type=setup.setup_type,
                trend_direction=view.trend_direction,
                recommendation_label=recommendation.label,
                recommendation_confidence=recommendation.confidence,
                invalidation_note=recommendation.invalidation_note,
                omni_score=omni_score,
            )
            inserted += int(self._insert_if_new(signal))
        return inserted

    def _insert_if_new(self, signal: SignalRecord) -> bool:
        if self._signal_repository.exists_by_dedupe_key(signal.dedupe_key):
            return False
        if self._signal_repository.find_recent_duplicate(signal) is not None:
            return False
        return self._signal_repository.insert_signal(signal)

    def _build_signal(
        self,
        *,
        ticker: str,
        name: str | None,
        origin: str,
        source_quality: str,
        strategy_family: str,
        score: float,
        trade_state: str,
        holding_period_label: str | None,
        entry_price: float | None,
        target_price: float | None,
        stop_loss_price: float | None,
        setup_type: str | None,
        trend_direction: str | None,
        recommendation_label: str,
        recommendation_confidence: str,
        invalidation_note: str | None,
        omni_score: float | None,
    ) -> SignalRecord:
        created_at = normalize_timestamp(datetime.now(UTC))
        feature_snapshot: dict[str, Any] = {
            "asset_type": AssetType.ETF,
            "ticker": ticker,
            "origin": origin,
            "omni_score": omni_score,
            "setup_type": setup_type,
        }
        return SignalRecord(
            signal_id=uuid4().hex,
            dedupe_key=build_dedupe_key(
                ticker=ticker,
                strategy_family=strategy_family,
                source_quality=source_quality,
                signal_origin=origin,
                created_at=created_at,
                trade_state=trade_state,
                recommendation_label=recommendation_label,
                entry_price=entry_price,
                asset_type=AssetType.ETF,
            ),
            created_at=created_at,
            ticker=ticker.upper().strip(),
            company_name=name or ticker.upper().strip(),
            strategy_family=strategy_family,
            signal_origin=origin,
            source_quality=source_quality,
            model_version=PERFORMANCE_MODEL_VERSION,
            recommendation_label=recommendation_label,
            recommendation_confidence=recommendation_confidence,
            trade_state=trade_state,
            holding_period_label=holding_period_label,
            score=score,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            trend_direction=trend_direction,
            setup_type=setup_type,
            invalidation_note=invalidation_note,
            accounting_quality_score=None,
            shenanigan_risk_score=None,
            accounting_data_completeness_score=None,
            accounting_assessment_confidence=None,
            news_score=None,
            news_impact=None,
            feature_snapshot_json=json.dumps(feature_snapshot, sort_keys=True),
            evaluated=0,
            asset_type=AssetType.ETF,
        )


def log_etf_signals(
    *,
    ticker: str,
    name: str | None,
    history: pd.DataFrame,
    omni_score: float | None,
    origin: str,
) -> int:
    return EtfSignalService().log_from_history(
        ticker=ticker,
        name=name,
        history=history,
        omni_score=omni_score,
        origin=origin,
    )


__all__ = ["EtfSignalService", "log_etf_signals"]
