from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from application.entry_trigger_lab_service import EntryTriggerLabService
from application.research_log_service import ResearchLogService
from config.performance import (
    COMMISSION_PER_TRADE,
    COST_FILTER_ENABLED,
    DEFAULT_TRADE_NOTIONAL,
    EDGE_EXPECTANCY_COMPONENT_CAP_PCT,
    EDGE_SCORE_WEIGHTS,
    HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT,
    MAX_TURNOVER_PENALTY,
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
from domain.signals.models import SignalRecord
from providers.market.market_provider import fetch_intraday_history, fetch_price_history
from storage.repositories.signal_repository import SignalRepository
from storage.repositories.ticker_repository import load_cached_ticker_data


def _history_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    history = pd.DataFrame(records)
    if history.empty:
        return pd.DataFrame()
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history[date_column] = pd.to_datetime(history[date_column]).dt.tz_localize(None)
    if date_column != "Date":
        history = history.rename(columns={date_column: "Date"})
    return history.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]


@dataclass(frozen=True)
class ExecutionPriceSnapshot:
    current_price: float | None
    price_source: str
    volatility_proxy_pct: float | None


class StrategyExecutionService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        entry_trigger_lab_service: EntryTriggerLabService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._signal_repository = signal_repository or SignalRepository(self._db_path)
        self._entry_trigger_lab_service = entry_trigger_lab_service or EntryTriggerLabService(
            signal_repository=self._signal_repository,
            db_path=self._db_path,
        )
        self._research_log_service = ResearchLogService()
        self._signal_repository.ensure_schema()

    def build_strategy_v1_execution_payload(
        self,
        limit: int = 100,
        *,
        pullback_pct_override: float | None = None,
        rule_label: str | None = None,
        is_shadow_benchmark: bool = False,
    ) -> dict[str, Any]:
        active_pullback_pct = float(pullback_pct_override) if pullback_pct_override is not None else STRATEGY_V1.pullback_pct
        signals = self._signal_repository.list_open_execution_candidates(
            trade_state=STRATEGY_V1.trade_state,
            min_score=STRATEGY_V1.min_score,
            strategy_families=SUPPORTED_SIGNAL_STRATEGIES,
            trend_direction=STRATEGY_V1.trend_direction,
            limit=limit,
        )
        price_cache: dict[tuple[str, str], ExecutionPriceSnapshot] = {}
        cohort_metric_cache: dict[str, dict[str, Any] | None] = {}
        ticker_turnover_cache: dict[str, dict[str, Any]] = {}
        signal_rows: list[dict[str, Any]] = []
        waiting_count = 0
        triggered_count = 0
        unavailable_count = 0
        now = datetime.now(tz=UTC)

        for signal in signals:
            snapshot = self._load_current_price(signal, price_cache)
            trigger_price = self._trigger_price(signal, active_pullback_pct)
            distance_to_trigger_pct = None
            if snapshot.current_price is not None and trigger_price not in (None, 0):
                distance_to_trigger_pct = ((float(snapshot.current_price) - float(trigger_price)) / float(trigger_price)) * 100.0
            signal_age_hours = (now - signal.created_at_datetime).total_seconds() / 3600.0
            historical_metrics = self._historical_metrics_for_signal(signal, cohort_metric_cache, active_pullback_pct)
            historical_expectancy_pct = historical_metrics.get("expectancy_pct") if historical_metrics else None
            estimated_cost_pct = self._estimated_transaction_cost_pct()
            net_expectancy_pct = (
                float(historical_expectancy_pct) - estimated_cost_pct
                if historical_expectancy_pct is not None
                else None
            )
            feature_snapshot = signal.feature_snapshot
            reward_risk = self._reward_risk_for_signal(signal, trigger_price)
            turnover_metrics = self._turnover_metrics_for_signal(signal, ticker_turnover_cache)
            if snapshot.current_price is None:
                trigger_status = "unavailable"
                unavailable_count += 1
            elif trigger_price is not None and snapshot.current_price <= trigger_price:
                trigger_status = "triggered"
                triggered_count += 1
            else:
                trigger_status = "waiting"
                waiting_count += 1

            signal_rows.append(
                {
                    "signal_id": signal.signal_id,
                    "created_at": signal.created_at,
                    "ticker": signal.ticker,
                    "company_name": signal.company_name,
                    "strategy_family": signal.strategy_family,
                    "score": round(signal.score),
                    "short_term_score": feature_snapshot.get("short_term_score") or feature_snapshot.get("signal_score"),
                    "long_term_score": feature_snapshot.get("long_term_score"),
                    "horizon_score": feature_snapshot.get("horizon_score"),
                    "alternate_horizon_score": feature_snapshot.get("alternate_horizon_score"),
                    "regime_label": feature_snapshot.get("regime_label") or self._regime_from_signal(signal),
                    "ranking_bucket": feature_snapshot.get("ranking_bucket"),
                    "recommendation_label": signal.recommendation_label,
                    "trade_state": signal.trade_state,
                    "holding_period_label": signal.holding_period_label,
                    "signal_entry_price": round(float(signal.entry_price), 2) if signal.entry_price is not None else None,
                    "target_price": round(float(signal.target_price), 2) if signal.target_price is not None else None,
                    "stop_loss_price": round(float(signal.stop_loss_price), 2) if signal.stop_loss_price is not None else None,
                    "current_price": round(float(snapshot.current_price), 2) if snapshot.current_price is not None else None,
                    "trigger_price": round(float(trigger_price), 2) if trigger_price is not None else None,
                    "distance_to_trigger_pct": round(float(distance_to_trigger_pct), 2) if distance_to_trigger_pct is not None else None,
                    "trigger_status": trigger_status,
                    "historical_cohort_expectancy_pct": historical_expectancy_pct,
                    "estimated_transaction_cost_pct": round(estimated_cost_pct, 4),
                    "net_historical_expectancy_pct": round(float(net_expectancy_pct), 4) if net_expectancy_pct is not None else None,
                    "historical_cohort_win_rate": historical_metrics.get("win_rate") if historical_metrics else None,
                    "historical_cohort_resolved_signals": historical_metrics.get("resolved_signals") if historical_metrics else None,
                    "historical_cohort_sample_quality": historical_metrics.get("sample_quality") if historical_metrics else None,
                    "historical_cohort_std_return_pct": historical_metrics.get("std_return_pct") if historical_metrics else None,
                    "historical_cohort_max_loss_pct": historical_metrics.get("max_loss_pct") if historical_metrics else None,
                    "historical_cohort_max_drawdown_pct": historical_metrics.get("max_drawdown_pct") if historical_metrics else None,
                    "historical_cohort_max_consecutive_losses": historical_metrics.get("max_consecutive_losses") if historical_metrics else None,
                    "historical_cohort_risk_penalty": historical_metrics.get("risk_penalty") if historical_metrics else None,
                    "historical_cohort_risk_flag": historical_metrics.get("risk_flag") if historical_metrics else None,
                    "signal_age_hours": round(float(signal_age_hours), 1),
                    "volatility_proxy_pct": round(float(snapshot.volatility_proxy_pct), 2) if snapshot.volatility_proxy_pct is not None else None,
                    "reward_risk_ratio": reward_risk.get("reward_risk_ratio"),
                    "reward_pct": reward_risk.get("reward_pct"),
                    "risk_pct": reward_risk.get("risk_pct"),
                    "reward_risk_status": reward_risk.get("reward_risk_status"),
                    "turnover_signal_count": turnover_metrics.get("turnover_signal_count"),
                    "turnover_lookback_days": turnover_metrics.get("turnover_lookback_days"),
                    "turnover_annualized_signals": turnover_metrics.get("turnover_annualized_signals"),
                    "turnover_penalty": turnover_metrics.get("turnover_penalty"),
                    "source_quality": signal.source_quality,
                    "price_source": snapshot.price_source,
                }
            )

        signal_rows.sort(key=lambda row: row["created_at"], reverse=True)
        signal_rows.sort(
            key=lambda row: 0 if row["trigger_status"] == "triggered" else 1 if row["trigger_status"] == "waiting" else 2
        )
        for row in signal_rows:
            row.update(self._time_stop_diagnostic(row))
            row["edge_quality_score"] = self._edge_quality_score(row)
            row["expectancy_conflict_flag"] = self._expectancy_conflict_flag(row)
            row.update(self._execution_decision(row))
            position_size, sizing_reason = self._position_size_and_reason(row)
            row["position_size"] = position_size
            row["sizing_reason"] = sizing_reason
            row["raw_weight"] = self._raw_weight(row)
        analysis_deduplicated_signal_rows = self._deduplicate_signal_rows_for_analysis(signal_rows)
        execution_deduplicated_signal_rows = self._deduplicate_signal_rows_for_execution(signal_rows)
        ranked_pretrigger_rows = sorted(
            execution_deduplicated_signal_rows,
            key=lambda row: (
                float(row.get("edge_quality_score") or 0.0),
                float(row.get("position_size") or 0.0),
                float(row.get("net_historical_expectancy_pct") or -9999.0),
                float(row.get("historical_cohort_expectancy_pct") or -9999.0),
                float(row.get("score") or 0.0),
                str(row.get("ticker") or ""),
                str(row.get("created_at") or ""),
            ),
            reverse=True,
        )
        for index, row in enumerate(ranked_pretrigger_rows, start=1):
            row["pretrigger_rank"] = index
        self._assign_regime_ranks(ranked_pretrigger_rows, rank_field="pretrigger_rank_within_regime")
        triggered_rows = [row for row in execution_deduplicated_signal_rows if row["trigger_status"] == "triggered"]
        ranked_triggered_rows = sorted(
            triggered_rows,
            key=lambda row: (
                float(row.get("edge_quality_score") or 0.0),
                float(row.get("net_historical_expectancy_pct") or -9999.0),
                float(row.get("historical_cohort_expectancy_pct") or -9999.0),
                float(row.get("score") or 0.0),
                str(row.get("ticker") or ""),
            ),
            reverse=True,
        )
        for index, row in enumerate(ranked_triggered_rows, start=1):
            row["rank"] = index
        self._assign_regime_ranks(ranked_triggered_rows, rank_field="rank_within_regime")

        cohort_payload = self._entry_trigger_lab_service.build_entry_trigger_payload(
            None,
            min_score=STRATEGY_V1.min_score,
            trend_direction=STRATEGY_V1.trend_direction,
            trade_state=STRATEGY_V1.trade_state,
        )
        historical_method = next(
            (
                row
                for row in cohort_payload.get("methods", [])
                if row.get("method_type") == STRATEGY_V1.entry_method
                and float(row.get("pullback_pct") or 0.0) == float(active_pullback_pct or 0.0)
            ),
            None,
        )

        preset = {
            "name": STRATEGY_V1.name,
            "rule_label": rule_label or f"Pullback {float(active_pullback_pct or 0.0):.2f}%",
            "is_shadow_benchmark": is_shadow_benchmark,
            "trade_state": STRATEGY_V1.trade_state,
            "min_score": STRATEGY_V1.min_score,
            "trend_direction": STRATEGY_V1.trend_direction,
            "strategy_family": "all_short_term",
            "entry_method": STRATEGY_V1.entry_method,
            "pullback_pct": active_pullback_pct,
            "exit_method": STRATEGY_V1.exit_method,
            "notes": STRATEGY_V1.notes,
            "min_reward_risk": STRATEGY_V1.min_reward_risk,
            "time_stop_max_holding_days": STRATEGY_V1.time_stop_max_holding_days,
            "time_stop_min_favorable_move_pct": STRATEGY_V1.time_stop_min_favorable_move_pct,
        }
        thresholds = self._threshold_snapshot(active_pullback_pct)
        self._research_log_service.log_execution_rows(
            execution_deduplicated_signal_rows,
            preset=preset,
            thresholds=thresholds,
        )

        return {
            "preset": preset,
            "thresholds": thresholds,
            "counts": {
                "total_signals": len(signal_rows),
                "analysis_deduplicated_signals": len(analysis_deduplicated_signal_rows),
                "execution_deduplicated_signals": len(execution_deduplicated_signal_rows),
                "waiting_signals": waiting_count,
                "triggered_signals": triggered_count,
                "analysis_deduplicated_triggered_signals": len(
                    [row for row in analysis_deduplicated_signal_rows if row["trigger_status"] == "triggered"]
                ),
                "execution_deduplicated_triggered_signals": len(ranked_triggered_rows),
                "accepted_triggered_signals": len(
                    [row for row in ranked_triggered_rows if row.get("execution_decision") == "accepted"]
                ),
                "rejected_triggered_signals": len(
                    [row for row in ranked_triggered_rows if row.get("execution_decision") == "rejected"]
                ),
                "unavailable_signals": unavailable_count,
            },
            "historical_expectancy": historical_method,
            "ranked_pretrigger_signals": ranked_pretrigger_rows,
            "top_pretrigger_signals": ranked_pretrigger_rows[:10],
            "ranked_triggered_signals": ranked_triggered_rows,
            "top_triggered_signals": ranked_triggered_rows[:5],
            "signals": signal_rows,
            "analysis_deduplicated_signals": analysis_deduplicated_signal_rows,
            "deduplicated_signals": execution_deduplicated_signal_rows,
            "portfolio_signals": execution_deduplicated_signal_rows,
        }

    @staticmethod
    def _trigger_price(signal: SignalRecord, pullback_pct: float | None) -> float | None:
        if signal.entry_price is None or pullback_pct is None:
            return None
        return float(signal.entry_price) * (1 - float(pullback_pct) / 100.0)

    def _load_current_price(
        self,
        signal: SignalRecord,
        price_cache: dict[tuple[str, str], ExecutionPriceSnapshot],
    ) -> ExecutionPriceSnapshot:
        cache_key = (signal.ticker, signal.strategy_family)
        if cache_key in price_cache:
            return price_cache[cache_key]

        snapshot = self._fetch_live_price(signal)
        if snapshot.current_price is None:
            snapshot = self._fetch_cached_price(signal)
        price_cache[cache_key] = snapshot
        return snapshot

    def _fetch_live_price(self, signal: SignalRecord) -> ExecutionPriceSnapshot:
        if signal.strategy_family == "short_term_day":
            history = fetch_intraday_history(signal.ticker, interval="15m", period="5d")
        else:
            history = fetch_price_history(signal.ticker, period="3mo")
        if history.empty:
            return ExecutionPriceSnapshot(current_price=None, price_source="unavailable", volatility_proxy_pct=None)
        latest_close = history["Close"].dropna()
        if latest_close.empty:
            return ExecutionPriceSnapshot(current_price=None, price_source="unavailable", volatility_proxy_pct=None)
        return ExecutionPriceSnapshot(
            current_price=float(latest_close.iloc[-1]),
            price_source="live",
            volatility_proxy_pct=self._volatility_proxy(history),
        )

    def _fetch_cached_price(self, signal: SignalRecord) -> ExecutionPriceSnapshot:
        cached = load_cached_ticker_data(signal.ticker) or {}
        records: list[dict[str, Any]]
        if signal.strategy_family == "short_term_day":
            records = cached.get("intraday_15m", []) or cached.get("history", [])
        else:
            records = cached.get("history", [])
        history = _history_from_records(records)
        if history.empty:
            return ExecutionPriceSnapshot(current_price=None, price_source="unavailable", volatility_proxy_pct=None)
        latest_close = history["Close"].dropna()
        if latest_close.empty:
            return ExecutionPriceSnapshot(current_price=None, price_source="unavailable", volatility_proxy_pct=None)
        return ExecutionPriceSnapshot(
            current_price=float(latest_close.iloc[-1]),
            price_source="cached_real",
            volatility_proxy_pct=self._volatility_proxy(history),
        )

    def _historical_metrics_for_signal(
        self,
        signal: SignalRecord,
        cohort_metric_cache: dict[str, dict[str, Any] | None],
        pullback_pct: float | None,
    ) -> dict[str, Any] | None:
        strategy_key = signal.strategy_family
        if strategy_key not in cohort_metric_cache:
            payload = self._entry_trigger_lab_service.build_entry_trigger_payload(
                strategy_key,
                min_score=STRATEGY_V1.min_score,
                trend_direction=STRATEGY_V1.trend_direction,
                trade_state=STRATEGY_V1.trade_state,
            )
            method_row = next(
                (
                    row
                    for row in payload.get("methods", [])
                    if row.get("method_type") == STRATEGY_V1.entry_method
                    and float(row.get("pullback_pct") or 0.0) == float(pullback_pct or 0.0)
                ),
                None,
            )
            cohort_metric_cache[strategy_key] = method_row

        strategy_metrics = cohort_metric_cache.get(strategy_key)
        if strategy_metrics and strategy_metrics.get("expectancy_pct") is not None:
            return strategy_metrics

        if "all_short_term" not in cohort_metric_cache:
            payload = self._entry_trigger_lab_service.build_entry_trigger_payload(
                None,
                min_score=STRATEGY_V1.min_score,
                trend_direction=STRATEGY_V1.trend_direction,
                trade_state=STRATEGY_V1.trade_state,
            )
            method_row = next(
                (
                    row
                    for row in payload.get("methods", [])
                    if row.get("method_type") == STRATEGY_V1.entry_method
                    and float(row.get("pullback_pct") or 0.0) == float(pullback_pct or 0.0)
                ),
                None,
            )
            cohort_metric_cache["all_short_term"] = method_row
        return cohort_metric_cache.get("all_short_term")

    @staticmethod
    def _volatility_proxy(history: pd.DataFrame) -> float | None:
        if history.empty:
            return None
        recent = history.tail(20).copy()
        if recent.empty:
            return None
        closes = recent["Close"].astype(float).replace(0, pd.NA)
        ranges = ((recent["High"].astype(float) - recent["Low"].astype(float)) / closes) * 100.0
        ranges = ranges.dropna()
        if ranges.empty:
            return None
        return float(ranges.mean())

    @staticmethod
    def _estimated_transaction_cost_pct() -> float:
        return estimated_round_trip_cost_pct()

    @staticmethod
    def _regime_from_signal(signal: SignalRecord) -> str:
        setup = (signal.setup_type or "").lower()
        if "mean" in setup or "reversion" in setup or "pullback" in setup:
            return "MEAN_REVERSION"
        return "MOMENTUM"

    @staticmethod
    def _reward_risk_for_signal(signal: SignalRecord, trigger_price: float | None) -> dict[str, Any]:
        entry_price = float(trigger_price or signal.entry_price or 0.0)
        target_price = float(signal.target_price or 0.0)
        stop_loss_price = float(signal.stop_loss_price or 0.0)
        if entry_price <= 0 or target_price <= 0 or stop_loss_price <= 0:
            return {
                "reward_risk_ratio": None,
                "reward_pct": None,
                "risk_pct": None,
                "reward_risk_status": "missing_levels",
            }

        reward = target_price - entry_price
        risk = entry_price - stop_loss_price
        if reward <= 0 or risk <= 0:
            return {
                "reward_risk_ratio": None,
                "reward_pct": round((reward / entry_price) * 100.0, 4),
                "risk_pct": round((risk / entry_price) * 100.0, 4),
                "reward_risk_status": "invalid_levels",
            }

        reward_pct = (reward / entry_price) * 100.0
        risk_pct = (risk / entry_price) * 100.0
        reward_risk_ratio = reward / risk
        status = "pass" if reward_risk_ratio >= float(MIN_REWARD_RISK) else "below_minimum"
        return {
            "reward_risk_ratio": round(reward_risk_ratio, 2),
            "reward_pct": round(reward_pct, 4),
            "risk_pct": round(risk_pct, 4),
            "reward_risk_status": status,
        }

    def _turnover_metrics_for_signal(
        self,
        signal: SignalRecord,
        ticker_turnover_cache: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        ticker = signal.ticker.upper().strip()
        if ticker in ticker_turnover_cache:
            return ticker_turnover_cache[ticker]

        lookback_days = max(int(TURNOVER_LOOKBACK_DAYS), 1)
        window_start = datetime.now(tz=UTC) - timedelta(days=lookback_days)
        recent_signals = [
            row
            for row in self._signal_repository.list_signals(limit=500, ticker=ticker)
            if row.strategy_family in SUPPORTED_SIGNAL_STRATEGIES and row.created_at_datetime >= window_start
        ]
        annualized = (len(recent_signals) / lookback_days) * 365.0
        if annualized <= float(HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT):
            penalty = 0.0
        else:
            excess_ratio = (annualized - float(HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT)) / max(
                float(HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT),
                1.0,
            )
            penalty = min(float(MAX_TURNOVER_PENALTY), excess_ratio * float(MAX_TURNOVER_PENALTY))

        metrics = {
            "turnover_signal_count": len(recent_signals),
            "turnover_lookback_days": lookback_days,
            "turnover_annualized_signals": round(annualized, 2),
            "turnover_penalty": round(penalty, 4),
        }
        ticker_turnover_cache[ticker] = metrics
        return metrics

    @staticmethod
    def _time_stop_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "time_stop_enabled": TIME_STOP_ENABLED,
            "time_stop_status": "disabled",
            "time_stop_min_favorable_move_pct": TIME_STOP_MIN_FAVORABLE_MOVE_PCT,
            "time_stop_max_holding_days": TIME_STOP_MAX_HOLDING_DAYS,
        }
        if not TIME_STOP_ENABLED:
            return payload
        if row.get("trigger_status") != "triggered":
            return {**payload, "time_stop_status": "not_started"}

        current_price = row.get("current_price")
        trigger_price = row.get("trigger_price")
        if current_price is None or trigger_price in (None, 0):
            return {**payload, "time_stop_status": "missing_price"}

        min_move = float(TIME_STOP_MIN_FAVORABLE_MOVE_PCT)
        favorable_price = float(trigger_price) * (1.0 + min_move / 100.0)
        if float(current_price) >= favorable_price:
            return {**payload, "time_stop_status": "progress_ok"}

        max_hours = float(TIME_STOP_MAX_HOLDING_DAYS) * 24.0
        if float(row.get("signal_age_hours") or 0.0) >= max_hours:
            return {**payload, "time_stop_status": "eligible_for_exit_or_downgrade"}
        return {**payload, "time_stop_status": "monitor"}

    @staticmethod
    def _execution_decision(row: dict[str, Any]) -> dict[str, str]:
        if row.get("trigger_status") == "unavailable":
            return {
                "execution_decision": "unavailable",
                "execution_rejection_reason": "Current price is unavailable.",
            }
        if row.get("trigger_status") == "waiting":
            return {
                "execution_decision": "waiting",
                "execution_rejection_reason": "Entry trigger has not fired yet.",
            }

        rejection_reasons: list[str] = []
        net_expectancy = row.get("net_historical_expectancy_pct")
        if COST_FILTER_ENABLED and (net_expectancy is None or float(net_expectancy) <= 0):
            rejection_reasons.append("Net expectancy after estimated costs is not positive.")

        reward_risk = row.get("reward_risk_ratio")
        if REWARD_RISK_FILTER_ENABLED:
            if reward_risk is None:
                rejection_reasons.append("Reward/risk could not be computed from entry, target, and stop.")
            elif float(reward_risk) < float(MIN_REWARD_RISK):
                rejection_reasons.append(f"Reward/risk is below {float(MIN_REWARD_RISK):.2f}.")

        if TIME_STOP_ENABLED and row.get("time_stop_status") == "eligible_for_exit_or_downgrade":
            rejection_reasons.append("Time-stop rule marks the signal for exit or downgrade.")

        if rejection_reasons:
            return {
                "execution_decision": "rejected",
                "execution_rejection_reason": " ".join(rejection_reasons),
            }
        return {
            "execution_decision": "accepted",
            "execution_rejection_reason": "",
        }

    @staticmethod
    def _expectancy_conflict_flag(row: dict[str, Any]) -> str:
        raw_score = float(row.get("score") or 0.0)
        expectancy = row.get("net_historical_expectancy_pct")
        if expectancy is None:
            return "no_expectancy_data"
        expectancy_pct = float(expectancy)
        if raw_score >= 75 and expectancy_pct <= 0:
            return "high_score_negative_net_expectancy"
        if raw_score < 60 and expectancy_pct >= 0.25:
            return "low_score_positive_net_expectancy"
        return "aligned_or_mild"

    @staticmethod
    def _threshold_snapshot(active_pullback_pct: float | None) -> dict[str, Any]:
        return {
            "min_short_term_scan_score": MIN_SHORT_TERM_SCAN_SCORE,
            "min_long_term_scan_score": MIN_LONG_TERM_SCAN_SCORE,
            "min_execution_score": STRATEGY_V1.min_score,
            "execution_pullback_pct": active_pullback_pct,
            "commission_per_trade": COMMISSION_PER_TRADE,
            "default_trade_notional": DEFAULT_TRADE_NOTIONAL,
            "slippage_bps": SLIPPAGE_BPS,
            "cost_filter_enabled": COST_FILTER_ENABLED,
            "edge_weights": {
                "raw_signal_score": EDGE_SCORE_WEIGHTS.raw_signal_score,
                "historical_expectancy": EDGE_SCORE_WEIGHTS.historical_expectancy,
                "trigger_proximity": EDGE_SCORE_WEIGHTS.trigger_proximity,
                "recency": EDGE_SCORE_WEIGHTS.recency,
                "lower_volatility": EDGE_SCORE_WEIGHTS.lower_volatility,
            },
            "reward_risk_filter_enabled": REWARD_RISK_FILTER_ENABLED,
            "min_reward_risk": MIN_REWARD_RISK,
            "time_stop_enabled": TIME_STOP_ENABLED,
            "time_stop_max_holding_days": TIME_STOP_MAX_HOLDING_DAYS,
            "time_stop_min_favorable_move_pct": TIME_STOP_MIN_FAVORABLE_MOVE_PCT,
            "turnover_lookback_days": TURNOVER_LOOKBACK_DAYS,
            "high_turnover_annualized_signal_count": HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT,
        }

    @staticmethod
    def _assign_regime_ranks(rows: list[dict[str, Any]], *, rank_field: str) -> None:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            bucket = str(row.get("ranking_bucket") or row.get("regime_label") or "UNKNOWN")
            buckets.setdefault(bucket, []).append(row)

        for bucket, bucket_rows in buckets.items():
            bucket_rows.sort(
                key=lambda row: (
                    float(row.get("edge_quality_score") or 0.0),
                    float(row.get("net_historical_expectancy_pct") or -9999.0),
                    float(row.get("score") or 0.0),
                    str(row.get("ticker") or ""),
                ),
                reverse=True,
            )
            for index, row in enumerate(bucket_rows, start=1):
                row[rank_field] = index
                row[f"{rank_field}_label"] = f"{index}/{len(bucket_rows)} in {bucket}"

    @staticmethod
    def _edge_quality_score(row: dict[str, Any]) -> float:
        score_component = min(max(float(row.get("score") or 0.0), 0.0), 100.0) / 100.0
        expectancy_source = row.get("net_historical_expectancy_pct")
        if expectancy_source is None:
            expectancy_source = row.get("historical_cohort_expectancy_pct")
        expectancy_pct = float(expectancy_source or 0.0)
        expectancy_component = min(max(expectancy_pct / float(EDGE_EXPECTANCY_COMPONENT_CAP_PCT), -1.0), 1.0)
        distance_pct = abs(float(row.get("distance_to_trigger_pct") or 0.0))
        trigger_component = max(0.0, 1.0 - min(distance_pct / 2.0, 1.0))
        age_hours = float(row.get("signal_age_hours") or 0.0)
        recency_component = max(0.0, 1.0 - min(age_hours / 72.0, 1.0))
        volatility_pct = float(row.get("volatility_proxy_pct") or 0.0)
        volatility_component = max(0.0, 1.0 - min(volatility_pct / 4.0, 1.0))
        total_weight = max(
            EDGE_SCORE_WEIGHTS.raw_signal_score
            + EDGE_SCORE_WEIGHTS.historical_expectancy
            + EDGE_SCORE_WEIGHTS.trigger_proximity
            + EDGE_SCORE_WEIGHTS.recency
            + EDGE_SCORE_WEIGHTS.lower_volatility,
            1e-9,
        )
        # If raw score and historical expectancy conflict, expectancy receives
        # the larger configurable weight and the row carries an explicit flag.
        composite = (
            EDGE_SCORE_WEIGHTS.raw_signal_score * score_component
            + EDGE_SCORE_WEIGHTS.historical_expectancy * max(expectancy_component, 0.0)
            + EDGE_SCORE_WEIGHTS.trigger_proximity * trigger_component
            + EDGE_SCORE_WEIGHTS.recency * recency_component
            + EDGE_SCORE_WEIGHTS.lower_volatility * volatility_component
        ) / total_weight
        return round(composite * 100.0, 1)

    @staticmethod
    def _position_size_and_reason(row: dict[str, Any]) -> tuple[float, str]:
        if row.get("execution_decision") == "rejected":
            return 0.0, str(row.get("execution_rejection_reason") or "Rejected by execution filter")

        expectancy_source = row.get("net_historical_expectancy_pct")
        if expectancy_source is None:
            expectancy_source = row.get("historical_cohort_expectancy_pct")
        expectancy_pct = float(expectancy_source or 0.0)
        if expectancy_pct <= 0:
            return 0.0, "Negative net expectancy"

        win_rate = float(row.get("historical_cohort_win_rate") or 0.0)
        resolved_signals = int(row.get("historical_cohort_resolved_signals") or 0)
        edge_quality_score = float(row.get("edge_quality_score") or 0.0)

        expectancy_component = min(expectancy_pct / 0.20, 1.0)
        win_rate_component = min(max(win_rate / 100.0, 0.0), 1.0)
        edge_component = min(max(edge_quality_score / 100.0, 0.0), 1.0)
        composite = (0.45 * expectancy_component) + (0.30 * edge_component) + (0.25 * win_rate_component)

        if resolved_signals > 30:
            sample_multiplier = 1.0
            sample_reason = "strong sample"
        elif resolved_signals >= 15:
            sample_multiplier = 0.7
            sample_reason = "moderate sample"
        else:
            sample_multiplier = 0.4
            sample_reason = "low sample"

        adjusted = composite * sample_multiplier
        if adjusted <= 0:
            return 0.0, "No actionable edge"
        size = max(0.05, min(adjusted, 1.0))

        if size < 0.30:
            strength_reason = "small edge"
        elif size < 0.55:
            strength_reason = "positive expectancy"
        elif size < 0.80:
            strength_reason = "strong edge"
        else:
            strength_reason = "highest edge"

        return round(size, 2), f"{strength_reason}, {sample_reason}"

    @staticmethod
    def _raw_weight(row: dict[str, Any]) -> float:
        position_size = float(row.get("position_size") or 0.0)
        risk_penalty = row.get("historical_cohort_risk_penalty")
        penalty = float(risk_penalty) if risk_penalty is not None else 0.0
        penalty = min(max(penalty, 0.0), 1.0)
        turnover_penalty = min(max(float(row.get("turnover_penalty") or 0.0), 0.0), 1.0)
        return round(position_size * (1.0 - penalty) * (1.0 - turnover_penalty), 4)

    @staticmethod
    def _deduplicate_signal_rows_for_analysis(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_group: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in rows:
            created_at = str(row.get("created_at") or "")
            time_bucket = created_at[:10] if len(created_at) >= 10 else created_at
            group_key = (
                str(row.get("ticker") or "").upper(),
                str(row.get("strategy_family") or ""),
                time_bucket,
            )
            existing = best_by_group.get(group_key)
            if existing is None:
                best_by_group[group_key] = row
                continue
            candidate_key = (
                float(row.get("edge_quality_score") or 0.0),
                float(row.get("net_historical_expectancy_pct") or -9999.0),
                float(row.get("historical_cohort_expectancy_pct") or -9999.0),
                float(row.get("score") or 0.0),
                str(row.get("created_at") or ""),
            )
            existing_key = (
                float(existing.get("edge_quality_score") or 0.0),
                float(existing.get("net_historical_expectancy_pct") or -9999.0),
                float(existing.get("historical_cohort_expectancy_pct") or -9999.0),
                float(existing.get("score") or 0.0),
                str(existing.get("created_at") or ""),
            )
            if candidate_key > existing_key:
                best_by_group[group_key] = row
        deduplicated = list(best_by_group.values())
        deduplicated.sort(key=lambda row: row["created_at"], reverse=True)
        deduplicated.sort(
            key=lambda row: 0 if row["trigger_status"] == "triggered" else 1 if row["trigger_status"] == "waiting" else 2
        )
        return deduplicated

    @staticmethod
    def _deduplicate_signal_rows_for_execution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_ticker: dict[str, dict[str, Any]] = {}
        for row in rows:
            ticker_key = str(row.get("ticker") or "").upper()
            if not ticker_key:
                continue
            existing = best_by_ticker.get(ticker_key)
            if existing is None:
                best_by_ticker[ticker_key] = row
                continue
            candidate_key = (
                float(row.get("edge_quality_score") or 0.0),
                float(row.get("net_historical_expectancy_pct") or -9999.0),
                float(row.get("historical_cohort_expectancy_pct") or -9999.0),
                float(row.get("score") or 0.0),
                str(row.get("created_at") or ""),
            )
            existing_key = (
                float(existing.get("edge_quality_score") or 0.0),
                float(existing.get("net_historical_expectancy_pct") or -9999.0),
                float(existing.get("historical_cohort_expectancy_pct") or -9999.0),
                float(existing.get("score") or 0.0),
                str(existing.get("created_at") or ""),
            )
            if candidate_key > existing_key:
                best_by_ticker[ticker_key] = row
        deduplicated = list(best_by_ticker.values())
        deduplicated.sort(key=lambda row: row["created_at"], reverse=True)
        deduplicated.sort(
            key=lambda row: 0 if row["trigger_status"] == "triggered" else 1 if row["trigger_status"] == "waiting" else 2
        )
        return deduplicated


__all__ = ["StrategyExecutionService"]
