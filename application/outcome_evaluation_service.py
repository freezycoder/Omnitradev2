from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from typing import Iterable
from uuid import uuid4

import pandas as pd

from config.performance import DAY_TRADE_HOLDING_DAYS, SUPPORTED_SIGNAL_STRATEGIES, SWING_TRADE_HOLDING_DAYS
from domain.evaluation.models import (
    OUTCOME_STATUS_EXPIRED,
    OUTCOME_STATUS_STOP,
    OUTCOME_STATUS_TARGET,
    OutcomeRecord,
)
from domain.signals.models import SignalRecord, normalize_timestamp, parse_timestamp
from providers.market.market_provider import fetch_intraday_history, fetch_price_history
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository
from storage.repositories.ticker_repository import load_cached_ticker_data


@dataclass(frozen=True)
class EvaluationWindow:
    strategy_family: str
    duration_days: int
    interval: str
    period: str


EVALUATION_WINDOWS = {
    "short_term_day": EvaluationWindow(
        strategy_family="short_term_day",
        duration_days=DAY_TRADE_HOLDING_DAYS,
        interval="15m",
        period="5d",
    ),
    "short_term_swing": EvaluationWindow(
        strategy_family="short_term_swing",
        duration_days=SWING_TRADE_HOLDING_DAYS,
        interval="1d",
        period="3mo",
    ),
}


def _history_from_records(records: list[dict]) -> pd.DataFrame:
    history = pd.DataFrame(records)
    if history.empty:
        return pd.DataFrame()
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history[date_column] = pd.to_datetime(history[date_column]).dt.tz_localize(None)
    if date_column != "Date":
        history = history.rename(columns={date_column: "Date"})
    return history.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]


class OutcomeEvaluationService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        outcome_repository: OutcomeRepository | None = None,
    ) -> None:
        self._signal_repository = signal_repository or SignalRepository()
        self._outcome_repository = outcome_repository or OutcomeRepository()

    def evaluate_open_short_term_signals(self, as_of: str | None = None) -> int:
        resolved_count = 0
        for strategy_family in SUPPORTED_SIGNAL_STRATEGIES:
            open_signals = self._signal_repository.list_open_signals(strategy_family=strategy_family, limit=1000)
            for signal in open_signals:
                if self._outcome_repository.get_by_signal_id(signal.signal_id) is not None:
                    continue
                outcome = self.evaluate_signal(signal, as_of=as_of)
                if outcome is None:
                    continue
                if self._outcome_repository.insert_outcome(outcome):
                    self._signal_repository.mark_evaluated(signal.signal_id)
                    resolved_count += 1
        return resolved_count

    def evaluate_signal(self, signal: SignalRecord, as_of: str | None = None) -> OutcomeRecord | None:
        if signal.strategy_family not in EVALUATION_WINDOWS:
            return None
        if signal.entry_price is None or signal.target_price is None or signal.stop_loss_price is None:
            return None

        as_of_dt = parse_timestamp(as_of) if as_of else pd.Timestamp.now(tz=UTC).to_pydatetime()
        window = EVALUATION_WINDOWS[signal.strategy_family]
        signal_dt = signal.created_at_datetime
        window_end = signal_dt + timedelta(days=window.duration_days)

        if signal.strategy_family == "short_term_day":
            history = self._load_day_trade_history(signal)
            return self._evaluate_intraday_signal(signal, history, as_of_dt, window_end, window)

        history = self._load_swing_history(signal)
        return self._evaluate_daily_signal(signal, history, as_of_dt, window_end, window)

    def _load_day_trade_history(self, signal: SignalRecord) -> pd.DataFrame:
        history = fetch_intraday_history(signal.ticker, interval="15m", period=EVALUATION_WINDOWS["short_term_day"].period)
        if history.empty:
            cached = load_cached_ticker_data(signal.ticker) or {}
            history = _history_from_records(cached.get("intraday_15m", []))
        if history.empty:
            return pd.DataFrame()
        history = history.sort_index()
        history.index = pd.to_datetime(history.index).tz_localize(None)
        return history

    def _load_swing_history(self, signal: SignalRecord) -> pd.DataFrame:
        history = fetch_price_history(signal.ticker, period=EVALUATION_WINDOWS["short_term_swing"].period)
        if history.empty:
            cached = load_cached_ticker_data(signal.ticker) or {}
            history = _history_from_records(cached.get("history", []))
        if history.empty:
            return pd.DataFrame()
        history = history.sort_index()
        history.index = pd.to_datetime(history.index).tz_localize(None)
        return history

    def _evaluate_intraday_signal(
        self,
        signal: SignalRecord,
        history: pd.DataFrame,
        as_of_dt,
        window_end,
        window: EvaluationWindow,
    ) -> OutcomeRecord | None:
        if history.empty:
            return None

        signal_ts = pd.Timestamp(signal.created_at_datetime).tz_localize(None)
        cutoff = min(pd.Timestamp(as_of_dt).tz_localize(None), pd.Timestamp(window_end).tz_localize(None))
        future = history[(history.index > signal_ts) & (history.index <= cutoff)].copy()
        if future.empty:
            return None

        resolution = self._resolve_from_bars(signal, future.itertuples(), is_intraday=True)
        if resolution is not None:
            return self._build_outcome_record(signal, future, resolution, window)

        if pd.Timestamp(as_of_dt).tz_localize(None) < pd.Timestamp(window_end).tz_localize(None):
            return None

        last_bar = future.iloc[-1]
        resolution = {
            "status": OUTCOME_STATUS_EXPIRED,
            "resolution_reason": "holding_window_expired_without_target_or_stop",
            "exit_price": float(last_bar["Close"]),
            "resolved_at": future.index[-1].to_pydatetime().replace(tzinfo=UTC),
            "first_target_hit_at": None,
            "first_stop_hit_at": None,
        }
        return self._build_outcome_record(signal, future, resolution, window)

    def _evaluate_daily_signal(
        self,
        signal: SignalRecord,
        history: pd.DataFrame,
        as_of_dt,
        window_end,
        window: EvaluationWindow,
    ) -> OutcomeRecord | None:
        if history.empty:
            return None

        signal_date = signal.created_at_date
        cutoff_date = min(as_of_dt.date(), window_end.date())
        future = history[(history.index.date > signal_date) & (history.index.date <= cutoff_date)].copy()
        if future.empty:
            return None

        resolution = self._resolve_from_bars(signal, future.itertuples(), is_intraday=False)
        if resolution is not None:
            return self._build_outcome_record(signal, future, resolution, window)

        if as_of_dt.date() < window_end.date():
            return None

        last_bar = future.iloc[-1]
        resolution = {
            "status": OUTCOME_STATUS_EXPIRED,
            "resolution_reason": "holding_window_expired_without_target_or_stop",
            "exit_price": float(last_bar["Close"]),
            "resolved_at": future.index[-1].to_pydatetime().replace(tzinfo=UTC),
            "first_target_hit_at": None,
            "first_stop_hit_at": None,
        }
        return self._build_outcome_record(signal, future, resolution, window)

    def _resolve_from_bars(
        self,
        signal: SignalRecord,
        bars: Iterable,
        *,
        is_intraday: bool,
    ) -> dict | None:
        target_hit_at = None
        stop_hit_at = None

        for bar in bars:
            bar_ts = pd.Timestamp(bar.Index).to_pydatetime().replace(tzinfo=UTC)
            bar_high = float(bar.High)
            bar_low = float(bar.Low)

            stop_hit = bar_low <= float(signal.stop_loss_price)
            target_hit = bar_high >= float(signal.target_price)

            if stop_hit:
                stop_hit_at = bar_ts
                return {
                    "status": OUTCOME_STATUS_STOP,
                    "resolution_reason": "stop_loss_hit_first_or_same_bar",
                    "exit_price": float(signal.stop_loss_price),
                    "resolved_at": bar_ts,
                    "first_target_hit_at": normalize_timestamp(target_hit_at) if target_hit_at else None,
                    "first_stop_hit_at": normalize_timestamp(stop_hit_at),
                }

            if target_hit:
                target_hit_at = bar_ts
                return {
                    "status": OUTCOME_STATUS_TARGET,
                    "resolution_reason": "target_hit_before_stop",
                    "exit_price": float(signal.target_price),
                    "resolved_at": bar_ts,
                    "first_target_hit_at": normalize_timestamp(target_hit_at),
                    "first_stop_hit_at": normalize_timestamp(stop_hit_at) if stop_hit_at else None,
                }

        return None

    def _build_outcome_record(
        self,
        signal: SignalRecord,
        future_bars: pd.DataFrame,
        resolution: dict,
        window: EvaluationWindow,
    ) -> OutcomeRecord:
        entry_price = float(signal.entry_price or 0.0)
        exit_price = float(resolution["exit_price"])
        highs = future_bars["High"].astype(float)
        lows = future_bars["Low"].astype(float)
        max_favorable_excursion_pct = ((float(highs.max()) - entry_price) / entry_price) * 100 if entry_price > 0 else None
        max_adverse_excursion_pct = ((float(lows.min()) - entry_price) / entry_price) * 100 if entry_price > 0 else None
        realized_return_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else None

        resolved_at = parse_timestamp(resolution["resolved_at"])
        holding_days = (resolved_at - signal.created_at_datetime).total_seconds() / 86400.0

        return OutcomeRecord(
            outcome_id=uuid4().hex,
            signal_id=signal.signal_id,
            evaluated_at=normalize_timestamp(pd.Timestamp.now(tz=UTC).to_pydatetime()),
            status=resolution["status"],
            resolution_reason=resolution["resolution_reason"],
            evaluation_window_bars=int(len(future_bars)),
            evaluation_window_days=window.duration_days,
            entry_price=signal.entry_price,
            exit_price=exit_price,
            target_price=signal.target_price,
            stop_loss_price=signal.stop_loss_price,
            max_favorable_excursion_pct=max_favorable_excursion_pct,
            max_adverse_excursion_pct=max_adverse_excursion_pct,
            realized_return_pct=realized_return_pct,
            holding_days=holding_days,
            first_target_hit_at=resolution.get("first_target_hit_at"),
            first_stop_hit_at=resolution.get("first_stop_hit_at"),
        )


__all__ = ["OutcomeEvaluationService"]
