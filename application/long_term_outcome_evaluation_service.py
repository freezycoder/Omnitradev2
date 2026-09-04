from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, timedelta
from uuid import uuid4

import pandas as pd

from config.performance import LONG_TERM_HORIZON_DAYS, SUPPORTED_LONG_TERM_STRATEGIES
from domain.evaluation.models import OUTCOME_STATUS_EXPIRED, OutcomeRecord
from domain.signals.models import SignalRecord, normalize_timestamp, parse_timestamp
from providers.market.market_provider import fetch_price_history
from storage.repositories.outcome_repository import OutcomeRepository
from storage.repositories.signal_repository import SignalRepository
from storage.repositories.ticker_repository import load_cached_ticker_data


@dataclass(frozen=True)
class LongTermEvaluationWindow:
    strategy_family: str
    duration_days: int
    period: str = "2y"


LONG_TERM_EVALUATION_WINDOWS = {
    strategy_family: LongTermEvaluationWindow(strategy_family=strategy_family, duration_days=days)
    for strategy_family, days in LONG_TERM_HORIZON_DAYS.items()
}


def _history_from_records(records: list[dict]) -> pd.DataFrame:
    history = pd.DataFrame(records)
    if history.empty:
        return pd.DataFrame()
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history[date_column] = pd.to_datetime(history[date_column]).dt.tz_localize(None)
    if date_column != "Date":
        history = history.rename(columns={date_column: "Date"})
    return history.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]].sort_index()


class LongTermOutcomeEvaluationService:
    """Evaluates long-term recommendation signals once their horizon has elapsed."""

    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        outcome_repository: OutcomeRepository | None = None,
    ) -> None:
        self._signal_repository = signal_repository or SignalRepository()
        self._outcome_repository = outcome_repository or OutcomeRepository()

    def evaluate_open_long_term_signals(self, as_of: str | None = None) -> int:
        resolved_count = 0
        for strategy_family in SUPPORTED_LONG_TERM_STRATEGIES:
            open_signals = self._signal_repository.list_open_signals(strategy_family=strategy_family, limit=2000)
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
        if signal.strategy_family not in LONG_TERM_EVALUATION_WINDOWS:
            return None
        if signal.entry_price is None:
            return None

        as_of_dt = parse_timestamp(as_of) if as_of else pd.Timestamp.now(tz=UTC).to_pydatetime()
        window = LONG_TERM_EVALUATION_WINDOWS[signal.strategy_family]
        window_end = signal.created_at_datetime + timedelta(days=window.duration_days)
        if as_of_dt < window_end:
            return None

        history = self._load_history(signal, period=window.period)
        if history.empty:
            return None

        signal_date = signal.created_at_date
        cutoff_date = min(as_of_dt.date(), window_end.date())
        future = history[(history.index.date > signal_date) & (history.index.date <= cutoff_date)].copy()
        if future.empty:
            return None

        exit_bar = future.iloc[-1]
        return self._build_outcome_record(
            signal=signal,
            future_bars=future,
            exit_price=float(exit_bar["Close"]),
            resolved_at=future.index[-1].to_pydatetime().replace(tzinfo=UTC),
            window=window,
        )

    def _load_history(self, signal: SignalRecord, *, period: str) -> pd.DataFrame:
        history = fetch_price_history(signal.ticker, period=period)
        if history.empty:
            cached = load_cached_ticker_data(signal.ticker) or {}
            history = _history_from_records(cached.get("history", []))
        if history.empty:
            return pd.DataFrame()
        history = history.sort_index()
        history.index = pd.to_datetime(history.index).tz_localize(None)
        return history

    def _build_outcome_record(
        self,
        *,
        signal: SignalRecord,
        future_bars: pd.DataFrame,
        exit_price: float,
        resolved_at,
        window: LongTermEvaluationWindow,
    ) -> OutcomeRecord:
        entry_price = float(signal.entry_price or 0.0)
        highs = future_bars["High"].astype(float)
        lows = future_bars["Low"].astype(float)
        max_favorable_excursion_pct = ((float(highs.max()) - entry_price) / entry_price) * 100 if entry_price > 0 else None
        max_adverse_excursion_pct = ((float(lows.min()) - entry_price) / entry_price) * 100 if entry_price > 0 else None
        realized_return_pct = ((exit_price - entry_price) / entry_price) * 100 if entry_price > 0 else None
        holding_days = (parse_timestamp(resolved_at) - signal.created_at_datetime).total_seconds() / 86400.0

        return OutcomeRecord(
            outcome_id=uuid4().hex,
            signal_id=signal.signal_id,
            evaluated_at=normalize_timestamp(pd.Timestamp.now(tz=UTC).to_pydatetime()),
            status=OUTCOME_STATUS_EXPIRED,
            resolution_reason=f"long_term_{window.duration_days}_day_horizon_elapsed",
            evaluation_window_bars=int(len(future_bars)),
            evaluation_window_days=window.duration_days,
            entry_price=signal.entry_price,
            exit_price=exit_price,
            target_price=None,
            stop_loss_price=None,
            max_favorable_excursion_pct=max_favorable_excursion_pct,
            max_adverse_excursion_pct=max_adverse_excursion_pct,
            realized_return_pct=realized_return_pct,
            holding_days=holding_days,
            first_target_hit_at=None,
            first_stop_hit_at=None,
        )


__all__ = ["LONG_TERM_EVALUATION_WINDOWS", "LongTermEvaluationWindow", "LongTermOutcomeEvaluationService"]
