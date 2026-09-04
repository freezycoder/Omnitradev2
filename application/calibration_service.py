from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from application.calibration_research_service import CalibrationResearchService
from application.performance_lab_service import PerformanceLabService
from config.performance import (
    COMMISSION_PER_TRADE,
    COST_FILTER_ENABLED,
    DEFAULT_TRADE_NOTIONAL,
    EDGE_SCORE_WEIGHTS,
    EXECUTION_PULLBACK_PCT,
    MIN_EXECUTION_SCORE,
    MIN_LONG_TERM_SCAN_SCORE,
    MIN_REWARD_RISK,
    MIN_SHORT_TERM_SCAN_SCORE,
    PERFORMANCE_DB_FILE,
    REWARD_RISK_FILTER_ENABLED,
    SLIPPAGE_BPS,
    STRATEGY_V1,
    SUPPORTED_SIGNAL_STRATEGIES,
    TIME_STOP_ENABLED,
    TIME_STOP_MAX_HOLDING_DAYS,
    TIME_STOP_MIN_FAVORABLE_MOVE_PCT,
    TURNOVER_LOOKBACK_DAYS,
    estimated_round_trip_cost_pct,
)
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository
from storage.sqlite import connection_scope


SCORE_BUCKET_ORDER = {"50-59": 0, "60-69": 1, "70-79": 2, "80+": 3}
CONFIDENCE_ORDER = {"Low": 0, "Balanced": 1, "Moderate": 2, "High": 3, "Very High": 4}
ACCOUNTING_RISK_ORDER = {
    "Low Risk (0-29)": 0,
    "Moderate Risk (30-49)": 1,
    "Elevated Risk (50-69)": 2,
    "High Risk (70+)": 3,
    "Unknown": 4,
}
ALTERNATIVE_SIGNAL_BAND_ORDER = {"Negative": 0, "Neutral": 1, "Positive": 2, "Unknown": 3}
RELATIVE_STRENGTH_BAND_ORDER = {
    "Laggard": 0,
    "Underperforming": 1,
    "Neutral": 2,
    "Outperforming": 3,
    "Leader": 4,
    "Unknown": 5,
}
EARNINGS_INTELLIGENCE_BAND_ORDER = {
    "Deteriorating": 0,
    "Cautious": 1,
    "Mixed": 2,
    "Constructive": 3,
    "Strong": 4,
    "Unknown": 5,
}
REGIME_ORDER = {"MOMENTUM": 0, "MEAN_REVERSION": 1, "UNKNOWN": 2}
MIN_RESOLVED_FOR_DIAGNOSTIC = 30


class CalibrationService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._signal_repository = signal_repository or SignalRepository(self._db_path)
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._performance_lab_service = PerformanceLabService(
            signal_repository=self._signal_repository,
            outcome_repository=self._outcome_repository,
            db_path=self._db_path,
        )
        self._signal_repository.ensure_schema()
        self._outcome_repository.ensure_schema()

    def build_payload(self) -> dict[str, Any]:
        score_buckets = self.get_score_bucket_analysis()
        strategy_comparison = self.get_strategy_comparison()
        regime_comparison = self.get_regime_comparison()
        confidence_analysis = self.get_confidence_analysis()
        accounting_risk_analysis = self.get_accounting_risk_analysis()
        alternative_signal_analysis = self.get_alternative_signal_analysis()
        relative_strength_analysis = self.get_relative_strength_analysis()
        earnings_intelligence_analysis = self.get_earnings_intelligence_analysis()
        active_thresholds = self.get_active_thresholds()
        payload = {
            "summary": {
                "resolved_signals": sum(int(row["resolved_signals"]) for row in score_buckets),
                "bucket_count": len(score_buckets),
                "regime_count": len(regime_comparison),
                "estimated_transaction_cost_pct": self._estimated_cost_pct(),
            },
            "active_thresholds": active_thresholds,
            "edge_weights": self.get_edge_weights(),
            "cost_model": self.get_cost_model(),
            "score_buckets": score_buckets,
            "strategy_comparison": strategy_comparison,
            "regime_comparison": regime_comparison,
            "confidence_analysis": confidence_analysis,
            "accounting_risk_analysis": accounting_risk_analysis,
            "alternative_signal_analysis": alternative_signal_analysis,
            "relative_strength_analysis": relative_strength_analysis,
            "earnings_intelligence_analysis": earnings_intelligence_analysis,
            "edge_filter": self._performance_lab_service.get_edge_filter_payload(),
            "research_calibration": CalibrationResearchService(
                outcome_repository=self._outcome_repository,
                db_path=self._db_path,
            ).build_payload(),
            "diagnostics": {
                "score_calibration": self._build_bucket_diagnostic(
                    score_buckets,
                    value_key="net_expectancy_pct",
                    title="Score calibration",
                    expectation="Higher score buckets should show stronger net expectancy and win rates after modeled costs.",
                ),
                "regime_alignment": self._build_regime_diagnostic(regime_comparison),
                "confidence_alignment": self._build_bucket_diagnostic(
                    confidence_analysis,
                    value_key="net_expectancy_pct",
                    title="Confidence alignment",
                    expectation="Higher recommendation confidence should correspond to stronger net expectancy and realized outcomes.",
                ),
                "accounting_risk_alignment": self._build_accounting_diagnostic(accounting_risk_analysis),
                "alternative_signal_validation": alternative_signal_analysis["diagnostic"],
                "relative_strength_validation": relative_strength_analysis["diagnostic"],
                "earnings_intelligence_validation": earnings_intelligence_analysis["diagnostic"],
            },
        }
        return payload

    def build_dashboard_payload(self) -> dict[str, Any]:
        return self.build_payload()

    def get_score_bucket_analysis(self) -> list[dict[str, Any]]:
        rows = self._outcome_repository.get_resolved_stats_by_score_bucket()
        return self._ordered_rows(rows, SCORE_BUCKET_ORDER, "score_bucket")

    def get_active_thresholds(self) -> dict[str, Any]:
        return {
            "min_short_term_scan_score": MIN_SHORT_TERM_SCAN_SCORE,
            "min_long_term_scan_score": MIN_LONG_TERM_SCAN_SCORE,
            "min_execution_score": MIN_EXECUTION_SCORE,
            "strategy_v1_min_score": STRATEGY_V1.min_score,
            "execution_pullback_pct": EXECUTION_PULLBACK_PCT,
            "strategy_v1_pullback_pct": STRATEGY_V1.pullback_pct,
            "reward_risk_filter_enabled": REWARD_RISK_FILTER_ENABLED,
            "min_reward_risk": MIN_REWARD_RISK,
            "time_stop_enabled": TIME_STOP_ENABLED,
            "time_stop_max_holding_days": TIME_STOP_MAX_HOLDING_DAYS,
            "time_stop_min_favorable_move_pct": TIME_STOP_MIN_FAVORABLE_MOVE_PCT,
            "turnover_lookback_days": TURNOVER_LOOKBACK_DAYS,
        }

    def get_edge_weights(self) -> dict[str, float]:
        return {
            "raw_signal_score": EDGE_SCORE_WEIGHTS.raw_signal_score,
            "historical_expectancy": EDGE_SCORE_WEIGHTS.historical_expectancy,
            "trigger_proximity": EDGE_SCORE_WEIGHTS.trigger_proximity,
            "recency": EDGE_SCORE_WEIGHTS.recency,
            "lower_volatility": EDGE_SCORE_WEIGHTS.lower_volatility,
        }

    def get_cost_model(self) -> dict[str, Any]:
        return {
            "commission_per_trade": COMMISSION_PER_TRADE,
            "default_trade_notional": DEFAULT_TRADE_NOTIONAL,
            "slippage_bps": SLIPPAGE_BPS,
            "cost_filter_enabled": COST_FILTER_ENABLED,
            "estimated_transaction_cost_pct": self._estimated_cost_pct(),
        }

    def get_strategy_comparison(self) -> list[dict[str, Any]]:
        query = """
            SELECT
                s.strategy_family,
                COUNT(*) AS total_signals,
                SUM(CASE WHEN o.signal_id IS NULL THEN 1 ELSE 0 END) AS open_signals,
                AVG(s.score) AS avg_score
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
            GROUP BY s.strategy_family
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query).fetchall()

        by_strategy = {str(row["strategy_family"]): row for row in rows}
        resolved_stats = {
            str(row["strategy_family"]): row for row in self._outcome_repository.get_resolved_stats_by_strategy()
        }
        payload: list[dict[str, Any]] = []
        for strategy in SUPPORTED_SIGNAL_STRATEGIES:
            signal_row = by_strategy.get(strategy)
            outcome_row = resolved_stats.get(strategy, {})
            if signal_row is None:
                payload.append(
                    {
                        "strategy_family": strategy,
                        "label": self._strategy_label(strategy),
                        "total_signals": 0,
                        "resolved_signals": 0,
                        "open_signals": 0,
                        "wins": 0,
                        "losses": 0,
                        "flats": 0,
                        "win_rate": None,
                        "avg_win_pct": None,
                        "avg_loss_pct": None,
                        "expectancy_pct": None,
                        "estimated_transaction_cost_pct": self._estimated_cost_pct(),
                        "net_expectancy_pct": None,
                        "avg_score": None,
                        "avg_return_pct": None,
                    }
                )
                continue
            expectation_metrics = self._with_cost_adjusted_expectancy(
                {
                    "expectancy_pct": outcome_row.get("expectancy_pct"),
                }
            )
            payload.append(
                {
                    "strategy_family": strategy,
                    "label": self._strategy_label(strategy),
                    "total_signals": int(signal_row["total_signals"] or 0),
                    "resolved_signals": int(outcome_row.get("resolved_signals") or 0),
                    "open_signals": int(signal_row["open_signals"] or 0),
                    "wins": int(outcome_row.get("wins") or 0),
                    "losses": int(outcome_row.get("losses") or 0),
                    "flats": int(outcome_row.get("flats") or 0),
                    "win_rate": outcome_row.get("win_rate"),
                    "avg_win_pct": outcome_row.get("avg_win_pct"),
                    "avg_loss_pct": outcome_row.get("avg_loss_pct"),
                    "expectancy_pct": outcome_row.get("expectancy_pct"),
                    "estimated_transaction_cost_pct": expectation_metrics["estimated_transaction_cost_pct"],
                    "net_expectancy_pct": expectation_metrics["net_expectancy_pct"],
                    "avg_score": round(float(signal_row["avg_score"]), 1) if signal_row["avg_score"] is not None else None,
                    "avg_return_pct": outcome_row.get("avg_return_pct"),
                }
            )
        return payload

    def get_regime_comparison(self) -> list[dict[str, Any]]:
        query = """
            SELECT
                s.signal_id,
                s.strategy_family,
                s.score,
                s.setup_type,
                s.feature_snapshot_json,
                o.realized_return_pct
            FROM signals s
            LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.strategy_family IN ('short_term_day', 'short_term_swing')
        """
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query).fetchall()

        grouped: dict[str, list[Any]] = {}
        for row in rows:
            grouped.setdefault(self._regime_label(row), []).append(row)

        payload: list[dict[str, Any]] = []
        for regime, regime_rows in grouped.items():
            resolved_rows = [row for row in regime_rows if row["realized_return_pct"] is not None]
            gross_stats = self._outcome_repository._rows_to_expectancy_stats(resolved_rows)
            stats = {
                **gross_stats,
                **self._with_cost_adjusted_expectancy(gross_stats),
            }
            scores = [float(row["score"]) for row in regime_rows if row["score"] is not None]
            payload.append(
                {
                    "regime": regime,
                    "label": self._regime_display_label(regime),
                    "total_signals": len(regime_rows),
                    "open_signals": len(regime_rows) - len(resolved_rows),
                    "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
                    **stats,
                }
            )

        payload.sort(key=lambda item: REGIME_ORDER.get(str(item.get("regime")), 999))
        return payload

    def get_confidence_analysis(self) -> list[dict[str, Any]]:
        rows = self._outcome_repository.get_resolved_stats_by_confidence_band()
        return self._ordered_rows(rows, CONFIDENCE_ORDER, "confidence_band")

    def get_accounting_risk_analysis(self) -> list[dict[str, Any]]:
        rows = self._outcome_repository.get_resolved_stats_by_accounting_risk_band()
        return self._ordered_rows(rows, ACCOUNTING_RISK_ORDER, "accounting_risk_band")

    def get_alternative_signal_analysis(self) -> dict[str, Any]:
        rows = self._outcome_repository.list_calibration_observations()
        parsed_rows: list[dict[str, Any]] = []
        for row in rows:
            try:
                snapshot = json.loads(row["feature_snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            shadow = snapshot.get("alternative_signal")
            if not isinstance(shadow, dict):
                impact = None
                coverage = None
                score = None
                band = "Unknown"
            else:
                impact_value = shadow.get("modeled_impact")
                impact = float(impact_value) if isinstance(impact_value, (int, float)) else None
                coverage_value = shadow.get("coverage_score")
                coverage = float(coverage_value) if isinstance(coverage_value, (int, float)) else None
                score_value = shadow.get("score")
                score = float(score_value) if isinstance(score_value, (int, float)) else None
                if impact is None:
                    band = "Unknown"
                elif impact > 0:
                    band = "Positive"
                elif impact < 0:
                    band = "Negative"
                else:
                    band = "Neutral"
            parsed_rows.append(
                {
                    "signal_id": row["signal_id"],
                    "ticker": row["ticker"],
                    "created_at": row["created_at"],
                    "realized_return_pct": row["realized_return_pct"],
                    "impact": impact,
                    "coverage": coverage,
                    "score": score,
                    "band": band,
                }
            )

        cohorts: list[dict[str, Any]] = []
        for band in ALTERNATIVE_SIGNAL_BAND_ORDER:
            scoped = [row for row in parsed_rows if row["band"] == band]
            if not scoped:
                continue
            stats = self._outcome_repository._rows_to_expectancy_stats(scoped)
            coverages = [float(row["coverage"]) for row in scoped if row["coverage"] is not None]
            impacts = [float(row["impact"]) for row in scoped if row["impact"] is not None]
            cohorts.append(
                {
                    "shadow_band": band,
                    "resolved_signals": int(stats["resolved_signals"] or 0),
                    "distinct_tickers": len({str(row["ticker"]) for row in scoped}),
                    "distinct_signal_dates": len({str(row["created_at"])[:10] for row in scoped}),
                    "avg_shadow_impact": round(sum(impacts) / len(impacts), 2) if impacts else None,
                    "avg_coverage_score": round(sum(coverages) / len(coverages), 1) if coverages else None,
                    **stats,
                    **self._with_cost_adjusted_expectancy(stats),
                }
            )
        cohorts.sort(key=lambda row: ALTERNATIVE_SIGNAL_BAND_ORDER[str(row["shadow_band"])])

        directional_rows = [
            row
            for row in parsed_rows
            if row["impact"] not in (None, 0)
            and row["realized_return_pct"] is not None
        ]
        directional_returns = [
            (1 if float(row["impact"]) > 0 else -1) * float(row["realized_return_pct"])
            for row in directional_rows
        ]
        gross_directional_expectancy = (
            sum(directional_returns) / len(directional_returns)
            if directional_returns
            else None
        )
        net_directional_expectancy = (
            gross_directional_expectancy - self._estimated_cost_pct()
            if gross_directional_expectancy is not None
            else None
        )
        distinct_dates = sorted({str(row["created_at"])[:10] for row in directional_rows})
        validation_dates = distinct_dates[max(1, int(len(distinct_dates) * 0.40)) :]
        block_size = max(1, (len(validation_dates) + 2) // 3)
        validation_blocks = [
            validation_dates[index : index + block_size]
            for index in range(0, len(validation_dates), block_size)
        ]
        validation_blocks = validation_blocks[:3]
        fold_rows: list[dict[str, Any]] = []
        for index, dates in enumerate(validation_blocks, start=1):
            date_set = set(dates)
            fold = [row for row in directional_rows if str(row["created_at"])[:10] in date_set]
            values = [
                (1 if float(row["impact"]) > 0 else -1) * float(row["realized_return_pct"])
                for row in fold
            ]
            expectancy = (
                sum(values) / len(values) - self._estimated_cost_pct()
                if values
                else None
            )
            fold_rows.append(
                {
                    "fold": index,
                    "resolved_signals": len(values),
                    "distinct_signal_dates": len(date_set),
                    "directional_net_expectancy_pct": round(expectancy, 2) if expectancy is not None else None,
                    "positive": expectancy is not None and expectancy > 0,
                }
            )
        positive_folds = sum(bool(row["positive"]) for row in fold_rows)
        average_coverage = (
            sum(float(row["coverage"]) for row in directional_rows if row["coverage"] is not None)
            / sum(row["coverage"] is not None for row in directional_rows)
            if any(row["coverage"] is not None for row in directional_rows)
            else None
        )
        requirements = {
            "minimum_resolved_signals": {
                "required": 50,
                "current": len(directional_rows),
                "passed": len(directional_rows) >= 50,
            },
            "minimum_distinct_signal_dates": {
                "required": 12,
                "current": len(distinct_dates),
                "passed": len(distinct_dates) >= 12,
            },
            "positive_validation_folds": {
                "required": 2,
                "current": positive_folds,
                "passed": positive_folds >= 2,
            },
            "positive_directional_net_expectancy": {
                "required": "> 0%",
                "current": round(net_directional_expectancy, 2) if net_directional_expectancy is not None else None,
                "passed": net_directional_expectancy is not None and net_directional_expectancy > 0,
            },
            "average_coverage": {
                "required": 70,
                "current": round(average_coverage, 1) if average_coverage is not None else None,
                "passed": average_coverage is not None and average_coverage >= 70,
            },
        }
        activation_ready = all(bool(requirement["passed"]) for requirement in requirements.values())
        diagnostic = {
            "title": "Alternative-signal validation",
            "status": "Ready for review" if activation_ready else "Collecting evidence",
            "summary": (
                "The shadow overlay has met every evidence gate. Activation still requires an explicit model review."
                if activation_ready
                else "The SEC, classified-news, and macro overlay remains shadow-only until every evidence gate passes."
            ),
            "expectation": (
                "Positive shadow impacts should outperform neutral cohorts, while negative impacts should identify weaker forward returns."
            ),
        }
        return {
            "mode": "shadow",
            "automatic_activation": False,
            "activation_ready": activation_ready,
            "directional_resolved_signals": len(directional_rows),
            "directional_gross_expectancy_pct": (
                round(gross_directional_expectancy, 2)
                if gross_directional_expectancy is not None
                else None
            ),
            "directional_net_expectancy_pct": (
                round(net_directional_expectancy, 2)
                if net_directional_expectancy is not None
                else None
            ),
            "requirements": requirements,
            "validation_folds": fold_rows,
            "cohorts": cohorts,
            "diagnostic": diagnostic,
        }

    def get_relative_strength_analysis(self) -> dict[str, Any]:
        rows = self._outcome_repository.list_calibration_observations()
        parsed_rows: list[dict[str, Any]] = []
        for row in rows:
            try:
                snapshot = json.loads(row["feature_snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            relative = snapshot.get("relative_strength")
            if not isinstance(relative, dict):
                score = None
                coverage = None
                band = "Unknown"
            else:
                score_value = relative.get("score")
                score = float(score_value) if isinstance(score_value, (int, float)) else None
                coverage_value = relative.get("coverage_score")
                coverage = float(coverage_value) if isinstance(coverage_value, (int, float)) else None
                if score is None:
                    band = "Unknown"
                elif score >= 70:
                    band = "Leader"
                elif score >= 58:
                    band = "Outperforming"
                elif score <= 30:
                    band = "Laggard"
                elif score <= 42:
                    band = "Underperforming"
                else:
                    band = "Neutral"
            parsed_rows.append(
                {
                    "signal_id": row["signal_id"],
                    "ticker": row["ticker"],
                    "created_at": row["created_at"],
                    "realized_return_pct": row["realized_return_pct"],
                    "score": score,
                    "coverage": coverage,
                    "band": band,
                }
            )

        cohorts: list[dict[str, Any]] = []
        for band in RELATIVE_STRENGTH_BAND_ORDER:
            scoped = [row for row in parsed_rows if row["band"] == band]
            if not scoped:
                continue
            stats = self._outcome_repository._rows_to_expectancy_stats(scoped)
            scores = [float(row["score"]) for row in scoped if row["score"] is not None]
            coverages = [float(row["coverage"]) for row in scoped if row["coverage"] is not None]
            cohorts.append(
                {
                    "relative_strength_band": band,
                    "resolved_signals": int(stats["resolved_signals"] or 0),
                    "distinct_tickers": len({str(row["ticker"]) for row in scoped}),
                    "distinct_signal_dates": len({str(row["created_at"])[:10] for row in scoped}),
                    "avg_relative_strength_score": round(sum(scores) / len(scores), 1) if scores else None,
                    "avg_coverage_score": round(sum(coverages) / len(coverages), 1) if coverages else None,
                    **stats,
                    **self._with_cost_adjusted_expectancy(stats),
                }
            )
        cohorts.sort(
            key=lambda row: RELATIVE_STRENGTH_BAND_ORDER[
                str(row["relative_strength_band"])
            ]
        )

        directional_rows = [
            row
            for row in parsed_rows
            if row["score"] is not None
            and float(row["score"]) != 50
            and row["realized_return_pct"] is not None
        ]
        directional_returns = [
            (1 if float(row["score"]) > 50 else -1) * float(row["realized_return_pct"])
            for row in directional_rows
        ]
        gross_directional_expectancy = (
            sum(directional_returns) / len(directional_returns)
            if directional_returns
            else None
        )
        net_directional_expectancy = (
            gross_directional_expectancy - self._estimated_cost_pct()
            if gross_directional_expectancy is not None
            else None
        )
        distinct_dates = sorted({str(row["created_at"])[:10] for row in directional_rows})
        validation_dates = distinct_dates[max(1, int(len(distinct_dates) * 0.40)) :]
        block_size = max(1, (len(validation_dates) + 2) // 3)
        validation_blocks = [
            validation_dates[index : index + block_size]
            for index in range(0, len(validation_dates), block_size)
        ][:3]
        fold_rows: list[dict[str, Any]] = []
        for index, dates in enumerate(validation_blocks, start=1):
            date_set = set(dates)
            fold = [row for row in directional_rows if str(row["created_at"])[:10] in date_set]
            values = [
                (1 if float(row["score"]) > 50 else -1) * float(row["realized_return_pct"])
                for row in fold
            ]
            expectancy = (
                sum(values) / len(values) - self._estimated_cost_pct()
                if values
                else None
            )
            fold_rows.append(
                {
                    "fold": index,
                    "resolved_signals": len(values),
                    "distinct_signal_dates": len(date_set),
                    "directional_net_expectancy_pct": round(expectancy, 2) if expectancy is not None else None,
                    "positive": expectancy is not None and expectancy > 0,
                }
            )
        positive_folds = sum(bool(row["positive"]) for row in fold_rows)
        coverages = [
            float(row["coverage"])
            for row in directional_rows
            if row["coverage"] is not None
        ]
        average_coverage = sum(coverages) / len(coverages) if coverages else None
        requirements = {
            "minimum_resolved_signals": {
                "required": 50,
                "current": len(directional_rows),
                "passed": len(directional_rows) >= 50,
            },
            "minimum_distinct_signal_dates": {
                "required": 12,
                "current": len(distinct_dates),
                "passed": len(distinct_dates) >= 12,
            },
            "positive_validation_folds": {
                "required": 2,
                "current": positive_folds,
                "passed": positive_folds >= 2,
            },
            "positive_directional_net_expectancy": {
                "required": "> 0%",
                "current": round(net_directional_expectancy, 2)
                if net_directional_expectancy is not None
                else None,
                "passed": net_directional_expectancy is not None
                and net_directional_expectancy > 0,
            },
            "average_coverage": {
                "required": 70,
                "current": round(average_coverage, 1)
                if average_coverage is not None
                else None,
                "passed": average_coverage is not None and average_coverage >= 70,
            },
        }
        activation_ready = all(bool(requirement["passed"]) for requirement in requirements.values())
        diagnostic = {
            "title": "Relative-strength validation",
            "status": "Ready for review" if activation_ready else "Collecting evidence",
            "summary": (
                "Market and sector leadership has met every evidence gate. Activation still requires an explicit model review."
                if activation_ready
                else "Relative strength remains shadow-only until leader cohorts demonstrate repeatable net expectancy."
            ),
            "expectation": (
                "Leaders and outperformers should produce stronger forward returns than neutral, underperforming, and lagging cohorts."
            ),
        }
        return {
            "mode": "shadow",
            "automatic_activation": False,
            "activation_ready": activation_ready,
            "directional_resolved_signals": len(directional_rows),
            "directional_gross_expectancy_pct": (
                round(gross_directional_expectancy, 2)
                if gross_directional_expectancy is not None
                else None
            ),
            "directional_net_expectancy_pct": (
                round(net_directional_expectancy, 2)
                if net_directional_expectancy is not None
                else None
            ),
            "requirements": requirements,
            "validation_folds": fold_rows,
            "cohorts": cohorts,
            "diagnostic": diagnostic,
        }

    def get_earnings_intelligence_analysis(self) -> dict[str, Any]:
        rows = self._outcome_repository.list_calibration_observations()
        parsed_rows: list[dict[str, Any]] = []
        for row in rows:
            try:
                snapshot = json.loads(row["feature_snapshot_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                snapshot = {}
            earnings = snapshot.get("earnings_intelligence")
            if not isinstance(earnings, dict):
                score = None
                coverage = None
                event_risk = "unknown"
                band = "Unknown"
            else:
                score_value = earnings.get("score")
                score = (
                    float(score_value)
                    if isinstance(score_value, (int, float))
                    else None
                )
                coverage_value = earnings.get("coverage_score")
                coverage = (
                    float(coverage_value)
                    if isinstance(coverage_value, (int, float))
                    else None
                )
                event_risk = str(earnings.get("event_risk") or "unknown")
                if score is None:
                    band = "Unknown"
                elif score >= 70:
                    band = "Strong"
                elif score >= 58:
                    band = "Constructive"
                elif score <= 30:
                    band = "Deteriorating"
                elif score <= 42:
                    band = "Cautious"
                else:
                    band = "Mixed"
            parsed_rows.append(
                {
                    "signal_id": row["signal_id"],
                    "ticker": row["ticker"],
                    "created_at": row["created_at"],
                    "realized_return_pct": row["realized_return_pct"],
                    "score": score,
                    "coverage": coverage,
                    "event_risk": event_risk,
                    "band": band,
                }
            )

        cohorts: list[dict[str, Any]] = []
        for band in EARNINGS_INTELLIGENCE_BAND_ORDER:
            scoped = [row for row in parsed_rows if row["band"] == band]
            if not scoped:
                continue
            stats = self._outcome_repository._rows_to_expectancy_stats(scoped)
            scores = [
                float(row["score"])
                for row in scoped
                if row["score"] is not None
            ]
            coverages = [
                float(row["coverage"])
                for row in scoped
                if row["coverage"] is not None
            ]
            cohorts.append(
                {
                    "earnings_intelligence_band": band,
                    "resolved_signals": int(stats["resolved_signals"] or 0),
                    "distinct_tickers": len(
                        {str(row["ticker"]) for row in scoped}
                    ),
                    "distinct_signal_dates": len(
                        {str(row["created_at"])[:10] for row in scoped}
                    ),
                    "high_event_risk_signals": sum(
                        row["event_risk"] in {"high", "elevated"}
                        for row in scoped
                    ),
                    "avg_earnings_intelligence_score": (
                        round(sum(scores) / len(scores), 1)
                        if scores
                        else None
                    ),
                    "avg_coverage_score": (
                        round(sum(coverages) / len(coverages), 1)
                        if coverages
                        else None
                    ),
                    **stats,
                    **self._with_cost_adjusted_expectancy(stats),
                }
            )
        cohorts.sort(
            key=lambda row: EARNINGS_INTELLIGENCE_BAND_ORDER[
                str(row["earnings_intelligence_band"])
            ]
        )

        directional_rows = [
            row
            for row in parsed_rows
            if row["score"] is not None
            and float(row["score"]) != 50
            and row["realized_return_pct"] is not None
        ]
        directional_returns = [
            (1 if float(row["score"]) > 50 else -1)
            * float(row["realized_return_pct"])
            for row in directional_rows
        ]
        gross_directional_expectancy = (
            sum(directional_returns) / len(directional_returns)
            if directional_returns
            else None
        )
        net_directional_expectancy = (
            gross_directional_expectancy - self._estimated_cost_pct()
            if gross_directional_expectancy is not None
            else None
        )
        distinct_dates = sorted(
            {str(row["created_at"])[:10] for row in directional_rows}
        )
        validation_dates = distinct_dates[
            max(1, int(len(distinct_dates) * 0.40)) :
        ]
        block_size = max(1, (len(validation_dates) + 2) // 3)
        validation_blocks = [
            validation_dates[index : index + block_size]
            for index in range(0, len(validation_dates), block_size)
        ][:3]
        fold_rows: list[dict[str, Any]] = []
        for index, dates in enumerate(validation_blocks, start=1):
            date_set = set(dates)
            fold = [
                row
                for row in directional_rows
                if str(row["created_at"])[:10] in date_set
            ]
            values = [
                (1 if float(row["score"]) > 50 else -1)
                * float(row["realized_return_pct"])
                for row in fold
            ]
            expectancy = (
                sum(values) / len(values) - self._estimated_cost_pct()
                if values
                else None
            )
            fold_rows.append(
                {
                    "fold": index,
                    "resolved_signals": len(values),
                    "distinct_signal_dates": len(date_set),
                    "directional_net_expectancy_pct": (
                        round(expectancy, 2)
                        if expectancy is not None
                        else None
                    ),
                    "positive": expectancy is not None and expectancy > 0,
                }
            )
        positive_folds = sum(bool(row["positive"]) for row in fold_rows)
        coverages = [
            float(row["coverage"])
            for row in directional_rows
            if row["coverage"] is not None
        ]
        average_coverage = (
            sum(coverages) / len(coverages)
            if coverages
            else None
        )
        requirements = {
            "minimum_resolved_signals": {
                "required": 50,
                "current": len(directional_rows),
                "passed": len(directional_rows) >= 50,
            },
            "minimum_distinct_signal_dates": {
                "required": 12,
                "current": len(distinct_dates),
                "passed": len(distinct_dates) >= 12,
            },
            "positive_validation_folds": {
                "required": 2,
                "current": positive_folds,
                "passed": positive_folds >= 2,
            },
            "positive_directional_net_expectancy": {
                "required": "> 0%",
                "current": (
                    round(net_directional_expectancy, 2)
                    if net_directional_expectancy is not None
                    else None
                ),
                "passed": (
                    net_directional_expectancy is not None
                    and net_directional_expectancy > 0
                ),
            },
            "average_coverage": {
                "required": 70,
                "current": (
                    round(average_coverage, 1)
                    if average_coverage is not None
                    else None
                ),
                "passed": (
                    average_coverage is not None
                    and average_coverage >= 70
                ),
            },
        }
        activation_ready = all(
            bool(requirement["passed"])
            for requirement in requirements.values()
        )
        diagnostic = {
            "title": "Earnings-intelligence validation",
            "status": (
                "Ready for review"
                if activation_ready
                else "Collecting evidence"
            ),
            "summary": (
                "Earnings execution and revision signals have met every evidence gate. Activation still requires an explicit model review."
                if activation_ready
                else "Earnings intelligence remains shadow-only until its score bands show repeatable net expectancy."
            ),
            "expectation": (
                "Strong and constructive earnings cohorts should outperform mixed, cautious, and deteriorating cohorts after costs."
            ),
        }
        return {
            "mode": "shadow",
            "automatic_activation": False,
            "activation_ready": activation_ready,
            "directional_resolved_signals": len(directional_rows),
            "directional_gross_expectancy_pct": (
                round(gross_directional_expectancy, 2)
                if gross_directional_expectancy is not None
                else None
            ),
            "directional_net_expectancy_pct": (
                round(net_directional_expectancy, 2)
                if net_directional_expectancy is not None
                else None
            ),
            "requirements": requirements,
            "validation_folds": fold_rows,
            "cohorts": cohorts,
            "diagnostic": diagnostic,
        }

    def _ordered_rows(
        self,
        rows: list[dict[str, Any]],
        ordering: dict[str, int],
        label_key: str,
    ) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for row in rows:
            resolved = int(row.get("resolved_signals") or row.get("total_resolved") or 0)
            payload.append(
                {
                    label_key: str(row.get(label_key)),
                    "resolved_signals": resolved,
                    "wins": int(row.get("wins") or 0),
                    "losses": int(row.get("losses") or 0),
                    "flats": int(row.get("flats") or 0),
                    "win_rate": row.get("win_rate"),
                    "avg_win_pct": row.get("avg_win_pct"),
                    "avg_loss_pct": row.get("avg_loss_pct"),
                    "avg_return_pct": row.get("avg_return_pct"),
                    "expectancy_pct": row.get("expectancy_pct"),
                    **self._with_cost_adjusted_expectancy(row),
                }
            )
        payload.sort(key=lambda item: ordering.get(item[label_key], 999))
        return payload

    def _with_cost_adjusted_expectancy(self, row: dict[str, Any]) -> dict[str, float | None]:
        expectancy = row.get("expectancy_pct")
        cost_pct = self._estimated_cost_pct()
        return {
            "estimated_transaction_cost_pct": cost_pct,
            "net_expectancy_pct": round(float(expectancy) - cost_pct, 2) if expectancy is not None else None,
        }

    def _build_bucket_diagnostic(
        self,
        rows: list[dict[str, Any]],
        *,
        value_key: str,
        title: str,
        expectation: str,
    ) -> dict[str, str]:
        valid_rows = [
            row
            for row in rows
            if int(row.get("resolved_signals") or 0) >= MIN_RESOLVED_FOR_DIAGNOSTIC
            and row.get(value_key) is not None
            and row.get("win_rate") is not None
        ]
        if len(valid_rows) < 2:
            return {
                "title": title,
                "status": "Insufficient data",
                "summary": "There are not enough resolved signals across multiple buckets to judge calibration yet.",
                "expectation": expectation,
            }

        values = [float(row[value_key]) for row in valid_rows]
        win_rates = [float(row["win_rate"]) for row in valid_rows]
        monotonic_values = all(curr >= prev for prev, curr in zip(values, values[1:]))
        monotonic_win_rates = all(curr >= prev for prev, curr in zip(win_rates, win_rates[1:]))

        if monotonic_values and monotonic_win_rates:
            status = "Aligned"
            summary = "Higher buckets are translating into stronger expectancy and win rates."
        elif values[-1] >= values[0] or win_rates[-1] >= win_rates[0]:
            status = "Mixed"
            summary = "The top buckets are directionally better, but the ladder is not consistently monotonic on expectancy."
        else:
            status = "Not aligned"
            summary = "Higher buckets are not delivering better expectancy on the current realized sample."

        return {
            "title": title,
            "status": status,
            "summary": summary,
            "expectation": expectation,
        }

    def _build_accounting_diagnostic(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        valid_rows = [
            row
            for row in rows
            if row.get("accounting_risk_band") != "Unknown"
            and int(row.get("resolved_signals") or 0) >= MIN_RESOLVED_FOR_DIAGNOSTIC
            and row.get("net_expectancy_pct") is not None
        ]
        if len(valid_rows) < 2:
            return {
                "title": "Accounting risk alignment",
                "status": "Insufficient data",
                "summary": "There are not enough resolved signals across accounting-risk bands to judge whether higher risk reduces expectancy.",
                "expectation": "Higher shenanigan risk should not behave like a positive expectancy tailwind.",
            }

        expectancy_values = [float(row["net_expectancy_pct"]) for row in valid_rows]
        if all(curr <= prev for prev, curr in zip(expectancy_values, expectancy_values[1:])):
            status = "Aligned"
            summary = "Expectancy weakens as accounting risk rises, which matches the intended skepticism."
        elif expectancy_values[-1] > expectancy_values[0]:
            status = "Mixed"
            summary = "Higher accounting-risk cohorts are not clearly underperforming on expectancy. The current sample does not strongly validate the risk penalty."
        else:
            status = "Mixed"
            summary = "Accounting-risk cohorts are not monotonic, but the highest-risk group is not outperforming the lowest-risk group on expectancy."

        return {
            "title": "Accounting risk alignment",
            "status": status,
            "summary": summary,
            "expectation": "Higher shenanigan risk should not behave like a positive expectancy tailwind.",
        }

    def _build_regime_diagnostic(self, rows: list[dict[str, Any]]) -> dict[str, str]:
        valid_rows = [
            row
            for row in rows
            if int(row.get("resolved_signals") or 0) >= MIN_RESOLVED_FOR_DIAGNOSTIC
            and row.get("net_expectancy_pct") is not None
        ]
        if not valid_rows:
            return {
                "title": "Regime alignment",
                "status": "Insufficient data",
                "summary": "There are not enough resolved momentum or mean-reversion signals to judge regime quality yet.",
                "expectation": "Momentum and mean-reversion should be calibrated separately because they earn edge in different market states.",
            }

        positive_rows = [row for row in valid_rows if float(row.get("net_expectancy_pct") or 0.0) > 0]
        best_row = max(valid_rows, key=lambda row: float(row.get("net_expectancy_pct") or float("-inf")))
        if len(positive_rows) == len(valid_rows):
            status = "Aligned"
            summary = f"Resolved regimes are positive after modeled costs; strongest current regime is {best_row.get('label')}."
        elif positive_rows:
            status = "Mixed"
            summary = f"Only some regimes are positive after modeled costs; strongest current regime is {best_row.get('label')}."
        else:
            status = "Not aligned"
            summary = "No resolved regime is currently positive after modeled costs."

        return {
            "title": "Regime alignment",
            "status": status,
            "summary": summary,
            "expectation": "Momentum and mean-reversion should be calibrated separately because they earn edge in different market states.",
        }

    @staticmethod
    def _regime_label(row: Any) -> str:
        try:
            snapshot = json.loads(row["feature_snapshot_json"] or "{}")
        except Exception:
            snapshot = {}
        regime = str(snapshot.get("regime_label") or "").upper().strip()
        if regime in REGIME_ORDER:
            return regime
        setup_type = str(row["setup_type"] or "").lower()
        if "mean" in setup_type or "reversion" in setup_type or "pullback" in setup_type:
            return "MEAN_REVERSION"
        if setup_type:
            return "MOMENTUM"
        return "UNKNOWN"

    @staticmethod
    def _regime_display_label(regime: str) -> str:
        if regime == "MOMENTUM":
            return "Momentum"
        if regime == "MEAN_REVERSION":
            return "Mean Reversion"
        return "Unknown"

    @staticmethod
    def _estimated_cost_pct() -> float:
        return round(estimated_round_trip_cost_pct(), 4)

    @staticmethod
    def _strategy_label(strategy_family: str) -> str:
        if strategy_family == "short_term_day":
            return "1-2 Day Trades"
        if strategy_family == "short_term_swing":
            return "5-15 Day Swings"
        return strategy_family


__all__ = ["CalibrationService"]
