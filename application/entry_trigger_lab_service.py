from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import pandas as pd

from application.outcome_evaluation_service import EVALUATION_WINDOWS, OutcomeEvaluationService
from config.performance import (
    ENTRY_TRIGGER_MIN_RESOLVED,
    ENTRY_TRIGGER_PULLBACK_LEVELS,
    PERFORMANCE_DB_FILE,
    STRATEGY_V1,
    SUPPORTED_SIGNAL_STRATEGIES,
    sample_quality_label,
)
from domain.signals.models import SignalRecord
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository
from storage.sqlite import connection_scope


@dataclass(frozen=True)
class EntryMethodDefinition:
    key: str
    label: str
    method_type: str
    pullback_pct: float | None = None


@dataclass(frozen=True)
class EntryMethodMetrics:
    method_key: str
    method_label: str
    method_type: str
    pullback_pct: float | None
    resolved_signals: int
    wins: int
    losses: int
    flats: int
    win_rate: float | None
    avg_return_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    expectancy_pct: float | None
    realized_pnl_pct: float | None
    pnl_vs_baseline_pct: float | None
    risk_adjusted_view: float | None
    std_return_pct: float | None
    max_loss_pct: float | None
    max_drawdown_pct: float | None
    max_consecutive_losses: int
    risk_penalty: float | None
    risk_flag: str
    low_sample: bool
    sample_note: str
    sample_quality: str
    triggered_signals: int
    cohort_size: int
    improvement_vs_baseline_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ENTRY_METHODS: tuple[EntryMethodDefinition, ...] = (
    EntryMethodDefinition(
        key="immediate",
        label="Immediate entry",
        method_type="immediate",
    ),
    *( 
        EntryMethodDefinition(
            key=f"pullback_{str(level).replace('.', '_')}",
            label=f"Pullback {level:.2f}%",
            method_type="pullback",
            pullback_pct=level,
        )
        for level in ENTRY_TRIGGER_PULLBACK_LEVELS
    ),
    EntryMethodDefinition(
        key="breakout_confirmation",
        label="Breakout confirmation",
        method_type="breakout_confirmation",
    ),
)


class EntryTriggerLabService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        outcome_repository: OutcomeRepository | None = None,
        outcome_evaluation_service: OutcomeEvaluationService | None = None,
        db_path: Path | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._signal_repository = signal_repository or SignalRepository(self._db_path)
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._evaluation_service = outcome_evaluation_service or OutcomeEvaluationService(
            signal_repository=self._signal_repository,
            outcome_repository=self._outcome_repository,
        )
        self._signal_repository.ensure_schema()
        self._outcome_repository.ensure_schema()

    def build_entry_trigger_payload(
        self,
        strategy_family: str | None,
        *,
        min_resolved: int = ENTRY_TRIGGER_MIN_RESOLVED,
        min_score: int = STRATEGY_V1.min_score,
        trend_direction: str = STRATEGY_V1.trend_direction,
        trade_state: str = STRATEGY_V1.trade_state,
    ) -> dict[str, Any]:
        if strategy_family is not None and strategy_family not in SUPPORTED_SIGNAL_STRATEGIES:
            raise ValueError(f"Unsupported strategy_family: {strategy_family}")

        resolved_signals = self._load_resolved_enter_now_signals(
            strategy_family=strategy_family,
            min_score=min_score,
            trend_direction=trend_direction,
            trade_state=trade_state,
        )
        cohort_size = len(resolved_signals)
        baseline = self._build_baseline_metrics(
            strategy_family=strategy_family,
            cohort_size=cohort_size,
            min_resolved=min_resolved,
            min_score=min_score,
            trend_direction=trend_direction,
            trade_state=trade_state,
        )

        history_cache: dict[tuple[str, str], pd.DataFrame] = {}
        method_metrics: list[EntryMethodMetrics] = [baseline]
        for definition in ENTRY_METHODS:
            if definition.method_type == "immediate":
                continue
            simulated_returns = self._simulate_method_returns(
                resolved_signals,
                definition,
                history_cache=history_cache,
            )
            method_metrics.append(
                self._summarize_returns(
                    definition=definition,
                    returns=simulated_returns,
                    cohort_size=cohort_size,
                    min_resolved=min_resolved,
                    baseline_expectancy=baseline.expectancy_pct,
                    baseline_pnl=baseline.realized_pnl_pct,
                )
            )

        qualifying = [metric for metric in method_metrics if metric.resolved_signals >= min_resolved]
        best_method = max(
            qualifying,
            key=lambda metric: (
                float(metric.expectancy_pct) if metric.expectancy_pct is not None else float("-inf"),
                float(metric.avg_return_pct) if metric.avg_return_pct is not None else float("-inf"),
                metric.resolved_signals,
            ),
        ) if qualifying else None

        return {
            "strategy_family": strategy_family or "all_short_term",
            "cohort_size": cohort_size,
            "min_resolved": min_resolved,
            "cohort_filters": {
                "trade_state": trade_state,
                "min_score": min_score,
                "trend_direction": trend_direction,
                "strategy_family": strategy_family,
            },
            "methods": [metric.to_dict() for metric in method_metrics],
            "qualifying_methods": [metric.to_dict() for metric in qualifying],
            "best_method": best_method.to_dict() if best_method else None,
        }

    def _load_resolved_enter_now_signals(
        self,
        *,
        strategy_family: str | None,
        min_score: int,
        trend_direction: str,
        trade_state: str,
    ) -> list[SignalRecord]:
        query = """
            SELECT s.*
            FROM signals s
            JOIN signal_outcomes o ON o.signal_id = s.signal_id
            WHERE s.trade_state = ?
              AND s.score >= ?
              AND s.entry_price IS NOT NULL
              AND s.target_price IS NOT NULL
              AND s.stop_loss_price IS NOT NULL
              AND o.realized_return_pct IS NOT NULL
        """
        params: list[object] = [trade_state, min_score]
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        if trend_direction.lower() != "all":
            query += " AND LOWER(COALESCE(s.trend_direction, '')) = ?"
            params.append(trend_direction.lower())
        query += " ORDER BY s.created_at ASC"
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()
        return [SignalRecord.from_row(row) for row in rows]

    def _build_baseline_metrics(
        self,
        *,
        strategy_family: str | None,
        cohort_size: int,
        min_resolved: int,
        min_score: int,
        trend_direction: str,
        trade_state: str,
    ) -> EntryMethodMetrics:
        query = """
            SELECT
                o.realized_return_pct
            FROM signal_outcomes o
            JOIN signals s ON s.signal_id = o.signal_id
            WHERE s.trade_state = ?
              AND s.score >= ?
              AND o.realized_return_pct IS NOT NULL
        """
        params: list[object] = [trade_state, min_score]
        if strategy_family:
            query += " AND s.strategy_family = ?"
            params.append(strategy_family)
        if trend_direction.lower() != "all":
            query += " AND LOWER(COALESCE(s.trend_direction, '')) = ?"
            params.append(trend_direction.lower())
        query += " ORDER BY o.evaluated_at ASC, s.created_at ASC"
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        definition = next(method for method in ENTRY_METHODS if method.method_type == "immediate")
        returns = [float(row["realized_return_pct"]) for row in rows if row["realized_return_pct"] is not None]
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        flats = sum(1 for value in returns if abs(value) < 1e-12)
        avg_win_pct = (sum(value for value in returns if value > 0) / wins) if wins else None
        avg_loss_pct = abs(sum(value for value in returns if value < 0) / losses) if losses else None
        avg_return_pct = (sum(returns) / len(returns)) if returns else None
        realized_pnl_pct = sum(returns) if returns else None
        risk_metrics = self._outcome_repository._risk_metrics_from_returns(returns)
        return self._build_metrics(
            definition=definition,
            resolved_signals=len(returns),
            wins=wins,
            losses=losses,
            flats=flats,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            avg_return_pct=avg_return_pct,
            realized_pnl_pct=realized_pnl_pct,
            risk_adjusted_view=(avg_return_pct / avg_loss_pct) if avg_return_pct is not None and avg_loss_pct not in (None, 0) else None,
            std_return_pct=risk_metrics.get("std_return_pct"),
            max_loss_pct=risk_metrics.get("max_loss_pct"),
            max_drawdown_pct=risk_metrics.get("max_drawdown_pct"),
            max_consecutive_losses=int(risk_metrics.get("max_consecutive_losses") or 0),
            risk_penalty=risk_metrics.get("risk_penalty"),
            risk_flag=str(risk_metrics.get("risk_flag") or "No data"),
            triggered_signals=cohort_size,
            cohort_size=cohort_size,
            min_resolved=min_resolved,
            baseline_expectancy=None,
            baseline_pnl=None,
        )

    def _simulate_method_returns(
        self,
        signals: list[SignalRecord],
        definition: EntryMethodDefinition,
        *,
        history_cache: dict[tuple[str, str], pd.DataFrame],
    ) -> list[float]:
        returns: list[float] = []
        for signal in signals:
            history = self._load_signal_history(signal, history_cache)
            if history.empty:
                continue
            future_bars = self._future_bars_for_signal(signal, history)
            if future_bars.empty:
                continue
            if definition.method_type == "pullback":
                realized_return = self._simulate_pullback_entry(
                    signal,
                    future_bars,
                    pullback_pct=float(definition.pullback_pct or 0.0),
                )
            else:
                realized_return = self._simulate_breakout_confirmation(signal, history, future_bars)
            if realized_return is not None and isfinite(float(realized_return)):
                returns.append(realized_return)
        return returns

    def _load_signal_history(
        self,
        signal: SignalRecord,
        history_cache: dict[tuple[str, str], pd.DataFrame],
    ) -> pd.DataFrame:
        cache_key = (signal.ticker, signal.strategy_family)
        if cache_key in history_cache:
            return history_cache[cache_key]
        if signal.strategy_family == "short_term_day":
            history = self._evaluation_service._load_day_trade_history(signal)
        else:
            history = self._evaluation_service._load_swing_history(signal)
        history_cache[cache_key] = history
        return history

    def _future_bars_for_signal(self, signal: SignalRecord, history: pd.DataFrame) -> pd.DataFrame:
        window = EVALUATION_WINDOWS[signal.strategy_family]
        signal_timestamp = pd.Timestamp(signal.created_at_datetime).tz_localize(None)
        window_end = signal.created_at_datetime + pd.Timedelta(days=window.duration_days)
        if signal.strategy_family == "short_term_day":
            cutoff = pd.Timestamp(window_end).tz_localize(None)
            future = history[(history.index > signal_timestamp) & (history.index <= cutoff)].copy()
        else:
            cutoff_date = window_end.date()
            future = history[(history.index.date > signal.created_at_date) & (history.index.date <= cutoff_date)].copy()
        return future.sort_index()

    def _simulate_pullback_entry(
        self,
        signal: SignalRecord,
        future_bars: pd.DataFrame,
        *,
        pullback_pct: float,
    ) -> float | None:
        if signal.entry_price is None or signal.target_price is None or signal.stop_loss_price is None:
            return None
        trigger_level = float(signal.entry_price) * (1 - pullback_pct / 100.0)
        for position, (_, bar) in enumerate(future_bars.iterrows()):
            if float(bar["Low"]) > trigger_level:
                continue
            entry_price = min(trigger_level, float(bar["Open"]))
            if not self._is_valid_long_bracket(
                entry_price=entry_price,
                stop_loss=float(signal.stop_loss_price),
                target_price=float(signal.target_price),
            ):
                return None
            return self._resolve_after_trigger(
                entry_price=entry_price,
                stop_loss=float(signal.stop_loss_price),
                target_price=float(signal.target_price),
                future_bars=future_bars,
                trigger_position=position,
            )
        return None

    def _simulate_breakout_confirmation(
        self,
        signal: SignalRecord,
        history: pd.DataFrame,
        future_bars: pd.DataFrame,
    ) -> float | None:
        if signal.target_price is None or signal.stop_loss_price is None:
            return None
        signal_bar_high = self._signal_bar_high(signal, history)
        if signal_bar_high is None:
            return None
        for position, (_, bar) in enumerate(future_bars.iterrows()):
            if float(bar["High"]) <= signal_bar_high:
                continue
            entry_price = max(signal_bar_high, float(bar["Open"]))
            if not self._is_valid_long_bracket(
                entry_price=entry_price,
                stop_loss=float(signal.stop_loss_price),
                target_price=float(signal.target_price),
            ):
                return None
            return self._resolve_after_trigger(
                entry_price=entry_price,
                stop_loss=float(signal.stop_loss_price),
                target_price=float(signal.target_price),
                future_bars=future_bars,
                trigger_position=position,
            )
        return None

    def _signal_bar_high(self, signal: SignalRecord, history: pd.DataFrame) -> float | None:
        if history.empty:
            return None
        if signal.strategy_family == "short_term_day":
            signal_timestamp = pd.Timestamp(signal.created_at_datetime).tz_localize(None)
            signal_window = history[history.index <= signal_timestamp]
        else:
            signal_window = history[[index.date() <= signal.created_at_date for index in history.index]]
        if signal_window.empty:
            return None
        return float(signal_window.iloc[-1]["High"])

    @staticmethod
    def _is_valid_long_bracket(*, entry_price: float, stop_loss: float, target_price: float) -> bool:
        if not all(isfinite(float(value)) for value in (entry_price, stop_loss, target_price)):
            return False
        return 0 < stop_loss < entry_price < target_price

    @staticmethod
    def _resolve_after_trigger(
        *,
        entry_price: float,
        stop_loss: float,
        target_price: float,
        future_bars: pd.DataFrame,
        trigger_position: int,
    ) -> float | None:
        triggered_bars = future_bars.iloc[trigger_position:]
        if triggered_bars.empty:
            return None

        for _, bar in triggered_bars.iterrows():
            bar_open = float(bar["Open"])
            bar_high = float(bar["High"])
            bar_low = float(bar["Low"])
            bar_close = float(bar["Close"])

            if bar_low <= stop_loss and bar_high >= target_price:
                return ((stop_loss - entry_price) / entry_price) * 100.0
            if bar_low <= stop_loss:
                return ((stop_loss - entry_price) / entry_price) * 100.0
            if bar_high >= target_price:
                return ((target_price - entry_price) / entry_price) * 100.0

            if bar_open <= stop_loss:
                return ((stop_loss - entry_price) / entry_price) * 100.0
            if bar_open >= target_price:
                return ((target_price - entry_price) / entry_price) * 100.0

            last_close = bar_close

        return ((last_close - entry_price) / entry_price) * 100.0

    def _summarize_returns(
        self,
        *,
        definition: EntryMethodDefinition,
        returns: list[float],
        cohort_size: int,
        min_resolved: int,
        baseline_expectancy: float | None,
        baseline_pnl: float | None,
    ) -> EntryMethodMetrics:
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        flats = sum(1 for value in returns if abs(value) < 1e-12)
        resolved_signals = len(returns)
        avg_win_pct = (sum(value for value in returns if value > 0) / wins) if wins else None
        avg_loss_pct = abs(sum(value for value in returns if value < 0) / losses) if losses else None
        avg_return_pct = (sum(returns) / resolved_signals) if resolved_signals else None
        realized_pnl_pct = sum(returns) if resolved_signals else None

        expectancy_pct = None
        if resolved_signals and avg_win_pct is not None and avg_loss_pct is not None:
            expectancy_pct = ((wins / resolved_signals) * avg_win_pct) - ((losses / resolved_signals) * avg_loss_pct)
        risk_adjusted_view = (expectancy_pct / avg_loss_pct) if expectancy_pct is not None and avg_loss_pct not in (None, 0) else None
        risk_metrics = self._outcome_repository._risk_metrics_from_returns(returns)

        return self._build_metrics(
            definition=definition,
            resolved_signals=resolved_signals,
            wins=wins,
            losses=losses,
            flats=flats,
            avg_win_pct=avg_win_pct,
            avg_loss_pct=avg_loss_pct,
            avg_return_pct=avg_return_pct,
            realized_pnl_pct=realized_pnl_pct,
            risk_adjusted_view=risk_adjusted_view,
            std_return_pct=risk_metrics.get("std_return_pct"),
            max_loss_pct=risk_metrics.get("max_loss_pct"),
            max_drawdown_pct=risk_metrics.get("max_drawdown_pct"),
            max_consecutive_losses=int(risk_metrics.get("max_consecutive_losses") or 0),
            risk_penalty=risk_metrics.get("risk_penalty"),
            risk_flag=str(risk_metrics.get("risk_flag") or "No data"),
            triggered_signals=resolved_signals,
            cohort_size=cohort_size,
            min_resolved=min_resolved,
            baseline_expectancy=baseline_expectancy,
            baseline_pnl=baseline_pnl,
        )

    @staticmethod
    def _build_metrics(
        *,
        definition: EntryMethodDefinition,
        resolved_signals: int,
        wins: int,
        losses: int,
        flats: int,
        avg_win_pct: float | None,
        avg_loss_pct: float | None,
        avg_return_pct: float | None,
        realized_pnl_pct: float | None,
        risk_adjusted_view: float | None,
        std_return_pct: float | None,
        max_loss_pct: float | None,
        max_drawdown_pct: float | None,
        max_consecutive_losses: int,
        risk_penalty: float | None,
        risk_flag: str,
        triggered_signals: int,
        cohort_size: int,
        min_resolved: int,
        baseline_expectancy: float | None,
        baseline_pnl: float | None,
    ) -> EntryMethodMetrics:
        win_rate = (wins / resolved_signals) * 100.0 if resolved_signals else None
        expectancy_pct = avg_return_pct if avg_return_pct is not None else None
        low_sample = 0 < resolved_signals < min_resolved
        if resolved_signals == 0:
            sample_note = "No resolved triggered sample yet"
        elif low_sample:
            sample_note = f"Early sample (<{min_resolved} resolved)"
        else:
            sample_note = "Established"

        improvement_vs_baseline = None
        if expectancy_pct is not None and baseline_expectancy is not None:
            improvement_vs_baseline = expectancy_pct - baseline_expectancy
        pnl_vs_baseline = None
        if realized_pnl_pct is not None and baseline_pnl is not None:
            pnl_vs_baseline = realized_pnl_pct - baseline_pnl

        return EntryMethodMetrics(
            method_key=definition.key,
            method_label=definition.label,
            method_type=definition.method_type,
            pullback_pct=definition.pullback_pct,
            resolved_signals=resolved_signals,
            wins=wins,
            losses=losses,
            flats=flats,
            win_rate=round(win_rate, 1) if win_rate is not None else None,
            avg_return_pct=round(avg_return_pct, 2) if avg_return_pct is not None else None,
            avg_win_pct=round(avg_win_pct, 2) if avg_win_pct is not None else None,
            avg_loss_pct=round(avg_loss_pct, 2) if avg_loss_pct is not None else None,
            expectancy_pct=round(expectancy_pct, 2) if expectancy_pct is not None else None,
            realized_pnl_pct=round(realized_pnl_pct, 2) if realized_pnl_pct is not None else None,
            pnl_vs_baseline_pct=round(pnl_vs_baseline, 2) if pnl_vs_baseline is not None else None,
            risk_adjusted_view=round(risk_adjusted_view, 2) if risk_adjusted_view is not None else None,
            std_return_pct=round(float(std_return_pct), 2) if std_return_pct is not None else None,
            max_loss_pct=round(float(max_loss_pct), 2) if max_loss_pct is not None else None,
            max_drawdown_pct=round(float(max_drawdown_pct), 2) if max_drawdown_pct is not None else None,
            max_consecutive_losses=max_consecutive_losses,
            risk_penalty=round(float(risk_penalty), 2) if risk_penalty is not None else None,
            risk_flag=risk_flag,
            low_sample=low_sample,
            sample_note=sample_note,
            sample_quality=sample_quality_label(resolved_signals),
            triggered_signals=triggered_signals,
            cohort_size=cohort_size,
            improvement_vs_baseline_pct=round(improvement_vs_baseline, 2) if improvement_vs_baseline is not None else None,
        )


__all__ = [
    "ENTRY_METHODS",
    "EntryMethodDefinition",
    "EntryMethodMetrics",
    "EntryTriggerLabService",
]
