from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Sequence
from uuid import uuid4

from application.ticker_service import TickerAnalysis
from config.performance import (
    LOGGABLE_SOURCE_QUALITIES,
    LOGGABLE_TRADE_STATES,
    PERFORMANCE_MODEL_VERSION,
)
from domain.signals.models import SignalRecord, build_dedupe_key, normalize_timestamp
from domain.signals.trade_levels import validate_long_trade_levels
from storage.repositories.signal_repository import SignalRepository


class SignalLogService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        model_version: str = PERFORMANCE_MODEL_VERSION,
    ) -> None:
        self._signal_repository = signal_repository or SignalRepository()
        self._model_version = model_version

    def log_scan_analyses(self, analyses: Sequence[TickerAnalysis]) -> int:
        inserted = 0
        for analysis in analyses:
            inserted += self.log_scan_analysis(analysis)
        return inserted

    def log_scan_analysis(self, analysis: TickerAnalysis) -> int:
        if not self._should_log_analysis(analysis):
            return 0

        inserted = 0
        day_signal = self.build_day_trade_signal(analysis, origin="scanner")
        if day_signal is not None:
            inserted += int(self._insert_if_new(day_signal))

        swing_signal = self.build_swing_trade_signal(analysis, origin="scanner")
        if swing_signal is not None:
            inserted += int(self._insert_if_new(swing_signal))

        return inserted

    def build_day_trade_signal(self, analysis: TickerAnalysis, origin: str = "scanner") -> SignalRecord | None:
        view = analysis.short_term_view.day_trade
        if view.trade_state_label not in LOGGABLE_TRADE_STATES:
            return None
        validation = validate_long_trade_levels(
            entry_price=view.entry_price,
            target_price=view.target_price,
            stop_loss_price=view.stop_loss_price,
            reference_price=analysis.snapshot.get("current_price"),
        )
        if not validation.valid:
            return None

        feature_snapshot = {
            "ticker": analysis.ticker,
            "company_name": analysis.company_name,
            "sector": analysis.sector,
            "data_source": analysis.data_source,
            "strategy_family": "short_term_day",
            "origin": origin,
            "short_term_score": analysis.short_term_view.score,
            "long_term_score": analysis.long_term_view.score,
            "signal_score": analysis.short_term_view.score,
            "horizon_score": view.score,
            "alternate_horizon_score": analysis.short_term_view.swing_trade.score,
            "recommendation_label": analysis.short_term_recommendation.label,
            "recommendation_confidence": analysis.short_term_recommendation.confidence,
            "trade_state": view.trade_state_label,
            "holding_period_label": view.holding_period_label,
            "setup_type": view.setup_type,
            "regime_label": view.regime_label,
            "regime_scores": view.regime_scores,
            "ranking_bucket": view.ranking_bucket,
            "entry_price": view.entry_price,
            "target_price": view.target_price,
            "stop_loss_price": view.stop_loss_price,
            "trend_direction": analysis.short_term_view.trend_direction,
            "news_score": analysis.short_term_view.news_score,
            "news_impact": analysis.short_term_view.news_impact,
            "alternative_signal": asdict(analysis.alternative_signal_view),
            "relative_strength": asdict(analysis.relative_strength_view),
            "earnings_intelligence": asdict(analysis.earnings_intelligence_view),
            "accounting_quality_score": analysis.accounting_quality_view.accounting_quality_score,
            "shenanigan_risk_score": analysis.accounting_quality_view.shenanigan_risk_score,
            "accounting_data_completeness_score": analysis.accounting_quality_view.accounting_data_completeness_score,
            "accounting_assessment_confidence": analysis.accounting_quality_view.accounting_assessment_confidence,
            "snapshot": analysis.snapshot,
            "reasons": view.reasons,
        }
        return self._build_signal_record(
            analysis=analysis,
            origin=origin,
            strategy_family="short_term_day",
            score=float(view.score),
            trade_state=view.trade_state_label,
            holding_period_label=view.holding_period_label,
            entry_price=view.entry_price,
            target_price=view.target_price,
            stop_loss_price=view.stop_loss_price,
            setup_type=view.setup_type,
            feature_snapshot=feature_snapshot,
        )

    def build_swing_trade_signal(self, analysis: TickerAnalysis, origin: str = "scanner") -> SignalRecord | None:
        view = analysis.short_term_view.swing_trade
        if view.trade_state_label not in LOGGABLE_TRADE_STATES:
            return None
        validation = validate_long_trade_levels(
            entry_price=view.entry_price,
            target_price=view.target_price,
            stop_loss_price=view.stop_loss_price,
            reference_price=analysis.snapshot.get("current_price"),
        )
        if not validation.valid:
            return None

        feature_snapshot = {
            "ticker": analysis.ticker,
            "company_name": analysis.company_name,
            "sector": analysis.sector,
            "data_source": analysis.data_source,
            "strategy_family": "short_term_swing",
            "origin": origin,
            "short_term_score": analysis.short_term_view.score,
            "long_term_score": analysis.long_term_view.score,
            "signal_score": analysis.short_term_view.score,
            "horizon_score": view.score,
            "alternate_horizon_score": analysis.short_term_view.day_trade.score,
            "recommendation_label": analysis.short_term_recommendation.label,
            "recommendation_confidence": analysis.short_term_recommendation.confidence,
            "trade_state": view.trade_state_label,
            "holding_period_label": view.holding_period_label,
            "setup_type": view.setup_type,
            "regime_label": view.regime_label,
            "regime_scores": view.regime_scores,
            "ranking_bucket": view.ranking_bucket,
            "entry_price": view.entry_price,
            "target_price": view.target_price,
            "stop_loss_price": view.stop_loss_price,
            "trend_direction": analysis.short_term_view.trend_direction,
            "news_score": analysis.short_term_view.news_score,
            "news_impact": analysis.short_term_view.news_impact,
            "alternative_signal": asdict(analysis.alternative_signal_view),
            "relative_strength": asdict(analysis.relative_strength_view),
            "earnings_intelligence": asdict(analysis.earnings_intelligence_view),
            "accounting_quality_score": analysis.accounting_quality_view.accounting_quality_score,
            "shenanigan_risk_score": analysis.accounting_quality_view.shenanigan_risk_score,
            "accounting_data_completeness_score": analysis.accounting_quality_view.accounting_data_completeness_score,
            "accounting_assessment_confidence": analysis.accounting_quality_view.accounting_assessment_confidence,
            "snapshot": analysis.snapshot,
            "reasons": view.reasons,
        }
        return self._build_signal_record(
            analysis=analysis,
            origin=origin,
            strategy_family="short_term_swing",
            score=float(view.score),
            trade_state=view.trade_state_label,
            holding_period_label=view.holding_period_label,
            entry_price=view.entry_price,
            target_price=view.target_price,
            stop_loss_price=view.stop_loss_price,
            setup_type=view.setup_type,
            feature_snapshot=feature_snapshot,
        )

    def _should_log_analysis(self, analysis: TickerAnalysis) -> bool:
        return analysis.data_source in LOGGABLE_SOURCE_QUALITIES

    def _insert_if_new(self, signal: SignalRecord) -> bool:
        if self._signal_repository.exists_by_dedupe_key(signal.dedupe_key):
            return False
        if self._signal_repository.find_recent_duplicate(signal) is not None:
            return False
        return self._signal_repository.insert_signal(signal)

    def _build_signal_record(
        self,
        *,
        analysis: TickerAnalysis,
        origin: str,
        strategy_family: str,
        score: float,
        trade_state: str | None,
        holding_period_label: str | None,
        entry_price: float | None,
        target_price: float | None,
        stop_loss_price: float | None,
        setup_type: str | None,
        feature_snapshot: dict,
    ) -> SignalRecord:
        created_at = normalize_timestamp(analysis.updated_at or datetime.now(UTC))
        dedupe_key = build_dedupe_key(
            ticker=analysis.ticker,
            strategy_family=strategy_family,
            source_quality=analysis.data_source,
            signal_origin=origin,
            created_at=created_at,
            trade_state=trade_state,
            recommendation_label=analysis.short_term_recommendation.label,
            entry_price=entry_price,
            model_version=self._model_version,
        )
        return SignalRecord(
            signal_id=uuid4().hex,
            dedupe_key=dedupe_key,
            created_at=created_at,
            ticker=analysis.ticker,
            company_name=analysis.company_name,
            strategy_family=strategy_family,
            signal_origin=origin,
            source_quality=analysis.data_source,
            model_version=self._model_version,
            recommendation_label=analysis.short_term_recommendation.label,
            recommendation_confidence=analysis.short_term_recommendation.confidence,
            trade_state=trade_state,
            holding_period_label=holding_period_label,
            score=score,
            entry_price=entry_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            trend_direction=analysis.short_term_view.trend_direction,
            setup_type=setup_type,
            invalidation_note=analysis.short_term_recommendation.invalidation_note,
            accounting_quality_score=float(analysis.accounting_quality_view.accounting_quality_score),
            shenanigan_risk_score=float(analysis.accounting_quality_view.shenanigan_risk_score),
            accounting_data_completeness_score=float(analysis.accounting_quality_view.accounting_data_completeness_score),
            accounting_assessment_confidence=analysis.accounting_quality_view.accounting_assessment_confidence,
            news_score=float(analysis.short_term_view.news_score),
            news_impact=float(analysis.short_term_view.news_impact),
            feature_snapshot_json=json.dumps(feature_snapshot, sort_keys=True),
            evaluated=0,
        )


__all__ = ["SignalLogService"]
