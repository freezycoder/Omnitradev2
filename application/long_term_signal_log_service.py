from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Sequence
from uuid import uuid4

from application.ticker_service import TickerAnalysis
from config.performance import (
    LOGGABLE_SOURCE_QUALITIES,
    LONG_TERM_HORIZON_DAYS,
    PERFORMANCE_MODEL_VERSION,
    SUPPORTED_LONG_TERM_STRATEGIES,
)
from config.thresholds import SCANNER_RULES
from domain.signals.models import SignalRecord, build_dedupe_key, normalize_timestamp
from storage.repositories.signal_repository import SignalRepository


@dataclass(frozen=True)
class LongTermHorizon:
    strategy_family: str
    label: str
    days: int


LONG_TERM_HORIZONS = tuple(
    LongTermHorizon(
        strategy_family=strategy_family,
        label=strategy_family.replace("long_term_", "").upper(),
        days=LONG_TERM_HORIZON_DAYS[strategy_family],
    )
    for strategy_family in SUPPORTED_LONG_TERM_STRATEGIES
)


class LongTermSignalLogService:
    """Logs scan-generated long-term recommendations for later horizon evaluation."""

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
        if not self._is_long_term_candidate(analysis):
            return 0

        inserted = 0
        for horizon in LONG_TERM_HORIZONS:
            signal = self._build_signal_record(analysis, horizon)
            inserted += int(self._insert_if_new(signal))
        return inserted

    def _should_log_analysis(self, analysis: TickerAnalysis) -> bool:
        return analysis.data_source in LOGGABLE_SOURCE_QUALITIES

    @staticmethod
    def _is_long_term_candidate(analysis: TickerAnalysis) -> bool:
        return (
            analysis.long_term_view.score >= SCANNER_RULES.long_term_min_score
            and analysis.long_term_recommendation.label in SCANNER_RULES.long_term_labels
        )

    def _insert_if_new(self, signal: SignalRecord) -> bool:
        if self._signal_repository.exists_by_dedupe_key(signal.dedupe_key):
            return False
        if self._signal_repository.find_recent_duplicate(signal) is not None:
            return False
        return self._signal_repository.insert_signal(signal)

    def _build_signal_record(self, analysis: TickerAnalysis, horizon: LongTermHorizon) -> SignalRecord:
        created_at = normalize_timestamp(analysis.updated_at or datetime.now(UTC))
        entry_price = self._entry_price(analysis)
        trend_direction = self._trend_direction(analysis)
        feature_snapshot = {
            "ticker": analysis.ticker,
            "company_name": analysis.company_name,
            "sector": analysis.sector,
            "data_source": analysis.data_source,
            "strategy_family": horizon.strategy_family,
            "origin": "scanner",
            "horizon_days": horizon.days,
            "long_term_score": analysis.long_term_view.score,
            "recommendation_label": analysis.long_term_recommendation.label,
            "recommendation_confidence": analysis.long_term_recommendation.confidence,
            "valuation_summary": analysis.valuation_summary,
            "entry_price": entry_price,
            "trend_direction": trend_direction,
            "news_score": analysis.long_term_view.news_score,
            "news_impact": analysis.long_term_view.news_impact,
            "alternative_signal": asdict(analysis.alternative_signal_view),
            "relative_strength": asdict(analysis.relative_strength_view),
            "earnings_intelligence": asdict(analysis.earnings_intelligence_view),
            "accounting_quality_score": analysis.accounting_quality_view.accounting_quality_score,
            "shenanigan_risk_score": analysis.accounting_quality_view.shenanigan_risk_score,
            "accounting_data_completeness_score": analysis.accounting_quality_view.accounting_data_completeness_score,
            "accounting_assessment_confidence": analysis.accounting_quality_view.accounting_assessment_confidence,
            "accounting_label": analysis.accounting_quality_view.label,
            "reasons": analysis.long_term_recommendation.reasons,
            "risks": analysis.long_term_recommendation.risks,
        }
        dedupe_key = build_dedupe_key(
            ticker=analysis.ticker,
            strategy_family=horizon.strategy_family,
            source_quality=analysis.data_source,
            signal_origin="scanner",
            created_at=created_at,
            trade_state="LONG TERM",
            recommendation_label=analysis.long_term_recommendation.label,
            entry_price=entry_price,
            model_version=self._model_version,
        )
        return SignalRecord(
            signal_id=uuid4().hex,
            dedupe_key=dedupe_key,
            created_at=created_at,
            ticker=analysis.ticker,
            company_name=analysis.company_name,
            strategy_family=horizon.strategy_family,
            signal_origin="scanner",
            source_quality=analysis.data_source,
            model_version=self._model_version,
            recommendation_label=analysis.long_term_recommendation.label,
            recommendation_confidence=analysis.long_term_recommendation.confidence,
            trade_state="LONG TERM",
            holding_period_label=horizon.label,
            score=float(analysis.long_term_view.score),
            entry_price=entry_price,
            target_price=None,
            stop_loss_price=None,
            trend_direction=trend_direction,
            setup_type="long_term_research",
            invalidation_note="Reassess if long-term trend support breaks or fundamentals deteriorate.",
            accounting_quality_score=float(analysis.accounting_quality_view.accounting_quality_score),
            shenanigan_risk_score=float(analysis.accounting_quality_view.shenanigan_risk_score),
            accounting_data_completeness_score=float(analysis.accounting_quality_view.accounting_data_completeness_score),
            accounting_assessment_confidence=analysis.accounting_quality_view.accounting_assessment_confidence,
            news_score=float(analysis.long_term_view.news_score),
            news_impact=float(analysis.long_term_view.news_impact),
            feature_snapshot_json=json.dumps(feature_snapshot, sort_keys=True),
            evaluated=0,
        )

    @staticmethod
    def _entry_price(analysis: TickerAnalysis) -> float | None:
        price = analysis.snapshot.get("current_price")
        if isinstance(price, (int, float)) and price > 0:
            return float(price)
        if analysis.enriched_history.empty:
            return None
        return float(analysis.enriched_history.iloc[-1]["Close"])

    @staticmethod
    def _trend_direction(analysis: TickerAnalysis) -> str:
        if analysis.enriched_history.empty:
            return "Unknown"
        latest = analysis.enriched_history.iloc[-1]
        close = float(latest["Close"])
        ma200 = float(latest["MA200"])
        if close > ma200:
            return "Bullish"
        if close < ma200:
            return "Bearish"
        return "Neutral"


__all__ = ["LONG_TERM_HORIZONS", "LongTermHorizon", "LongTermSignalLogService"]
