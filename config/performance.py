from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.settings import DATA_DIR
from domain.backtest.thresholds import DEFAULT_THRESHOLD_SET


PERFORMANCE_DB_FILE: Path = DATA_DIR / "omnitrade.db"
PERFORMANCE_MODEL_VERSION = "v5-earnings-intelligence-shadow-1"

SUPPORTED_SIGNAL_STRATEGIES = ("short_term_day", "short_term_swing")
SUPPORTED_LONG_TERM_STRATEGIES = ("long_term_3m", "long_term_6m", "long_term_12m")
ALL_SIGNAL_STRATEGIES = (*SUPPORTED_SIGNAL_STRATEGIES, *SUPPORTED_LONG_TERM_STRATEGIES)
LOGGABLE_SOURCE_QUALITIES = ("live", "cached_real")
LOGGABLE_TRADE_STATES = ("ENTER NOW", "WAIT FOR PULLBACK")
SKIPPED_SOURCE_QUALITIES = ("demo",)

SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT = 0.75
SIGNAL_DEDUPE_LOOKBACK_DAYS = 1

DAY_TRADE_HOLDING_DAYS = 2
SWING_TRADE_HOLDING_DAYS = 15
LONG_TERM_HORIZON_DAYS = {
    "long_term_3m": 90,
    "long_term_6m": 180,
    "long_term_12m": 365,
}

SQLITE_TIMEOUT_SECONDS = 30.0

EDGE_FILTER_THRESHOLDS = (
    ("All", None),
    ("70+", 70),
    ("75+", 75),
    ("80+", 80),
    ("85+", 85),
)
LOW_SAMPLE_RESOLVED_THRESHOLD = 15

ENTRY_TRIGGER_PULLBACK_LEVELS = (0.50, 0.75, 1.00)
ENTRY_TRIGGER_MIN_RESOLVED = 15
PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES = 15

MIN_SHORT_TERM_SCAN_SCORE = DEFAULT_THRESHOLD_SET.scanner.min_short_term_scan_score
MIN_LONG_TERM_SCAN_SCORE = DEFAULT_THRESHOLD_SET.scanner.min_long_term_scan_score
MIN_EXECUTION_SCORE = DEFAULT_THRESHOLD_SET.execution.min_execution_score
EXECUTION_PULLBACK_PCT = DEFAULT_THRESHOLD_SET.execution.execution_pullback_pct


@dataclass(frozen=True)
class EdgeScoreWeights:
    raw_signal_score: float = 0.30
    historical_expectancy: float = 0.40
    trigger_proximity: float = 0.15
    recency: float = 0.10
    lower_volatility: float = 0.05


EDGE_SCORE_WEIGHTS = EdgeScoreWeights()
EDGE_EXPECTANCY_COMPONENT_CAP_PCT = 0.50

COMMISSION_PER_TRADE = 0.0
DEFAULT_TRADE_NOTIONAL = 10_000.0
SLIPPAGE_BPS = 0.0
COST_FILTER_ENABLED = False

TURNOVER_LOOKBACK_DAYS = 90
HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT = 48.0
MAX_TURNOVER_PENALTY = 0.30

REWARD_RISK_FILTER_ENABLED = False
MIN_REWARD_RISK = 2.0

TIME_STOP_ENABLED = False
TIME_STOP_MAX_HOLDING_DAYS = 5
TIME_STOP_MIN_FAVORABLE_MOVE_PCT = 1.0

RESEARCH_LOGGING_ENABLED = False
RESEARCH_LOG_DIR = DATA_DIR / "research_logs"
RESEARCH_EXECUTION_LOG_FILE = RESEARCH_LOG_DIR / "strategy_execution_diagnostics.jsonl"


def estimated_round_trip_cost_pct() -> float:
    notional = max(float(DEFAULT_TRADE_NOTIONAL or 0.0), 1.0)
    commission_pct = ((float(COMMISSION_PER_TRADE) * 2.0) / notional) * 100.0
    slippage_pct = (float(SLIPPAGE_BPS) * 2.0) / 100.0
    return max(0.0, commission_pct + slippage_pct)


def performance_assumptions_snapshot() -> dict[str, object]:
    estimated_cost_pct = estimated_round_trip_cost_pct()
    transaction_costs_configured = bool(
        float(COMMISSION_PER_TRADE) > 0.0 or float(SLIPPAGE_BPS) > 0.0
    )
    return {
        "reporting_basis": (
            "gross_and_configured_net"
            if transaction_costs_configured
            else "gross_before_costs"
        ),
        "result_label": (
            "Gross and configured net"
            if transaction_costs_configured
            else "Gross, before costs"
        ),
        "transaction_costs_configured": transaction_costs_configured,
        "net_expectancy_modeled": transaction_costs_configured,
        "commission_per_side": float(COMMISSION_PER_TRADE),
        "default_trade_notional": float(DEFAULT_TRADE_NOTIONAL),
        "slippage_bps_per_side": float(SLIPPAGE_BPS),
        "estimated_round_trip_cost_pct": round(estimated_cost_pct, 4),
        "cost_filter_enabled": bool(COST_FILTER_ENABLED),
        "reward_risk_filter_enabled": bool(REWARD_RISK_FILTER_ENABLED),
        "min_reward_risk": float(MIN_REWARD_RISK),
        "time_stop_enabled": bool(TIME_STOP_ENABLED),
        "time_stop_max_holding_days": int(TIME_STOP_MAX_HOLDING_DAYS),
        "time_stop_min_favorable_move_pct": float(TIME_STOP_MIN_FAVORABLE_MOVE_PCT),
        "warning": (
            None
            if transaction_costs_configured
            else (
                "Commission and slippage are both zero. Treat performance as gross, "
                "before transaction costs; configured net expectancy is not a realistic net estimate."
            )
        ),
    }


@dataclass(frozen=True)
class StrategyPreset:
    name: str
    trade_state: str
    min_score: int
    trend_direction: str
    entry_method: str
    pullback_pct: float | None
    exit_method: str
    notes: str
    require_positive_net_expectancy: bool = COST_FILTER_ENABLED
    min_reward_risk: float | None = MIN_REWARD_RISK
    time_stop_max_holding_days: int | None = TIME_STOP_MAX_HOLDING_DAYS
    time_stop_min_favorable_move_pct: float | None = TIME_STOP_MIN_FAVORABLE_MOVE_PCT


STRATEGY_V1 = StrategyPreset(
    name="Strategy_v1",
    trade_state="ENTER NOW",
    min_score=MIN_EXECUTION_SCORE,
    trend_direction="all",
    entry_method="pullback",
    pullback_pct=EXECUTION_PULLBACK_PCT,
    exit_method="existing_target_stop",
    notes=(
        f"ENTER NOW short-term signals with score {MIN_EXECUTION_SCORE} or higher, across all trends and both "
        f"short-term strategies, entered only after a {EXECUTION_PULLBACK_PCT:.2f}% pullback while preserving the "
        "existing target and stop. Pullback 1.00% remains the conservative shadow benchmark."
    ),
)

STRATEGY_PRESETS = {
    STRATEGY_V1.name: STRATEGY_V1,
}


def get_strategy_preset(name: str) -> StrategyPreset | None:
    return STRATEGY_PRESETS.get(name)


def sample_quality_label(resolved_signals: int) -> str:
    if resolved_signals >= 50:
        return "Strong"
    if resolved_signals >= 20:
        return "Moderate"
    return "Weak"

__all__ = [
    "ALL_SIGNAL_STRATEGIES",
    "DAY_TRADE_HOLDING_DAYS",
    "EDGE_FILTER_THRESHOLDS",
    "EDGE_EXPECTANCY_COMPONENT_CAP_PCT",
    "EDGE_SCORE_WEIGHTS",
    "EdgeScoreWeights",
    "ENTRY_TRIGGER_MIN_RESOLVED",
    "ENTRY_TRIGGER_PULLBACK_LEVELS",
    "COMMISSION_PER_TRADE",
    "COST_FILTER_ENABLED",
    "DEFAULT_TRADE_NOTIONAL",
    "EXECUTION_PULLBACK_PCT",
    "HIGH_TURNOVER_ANNUALIZED_SIGNAL_COUNT",
    "MAX_TURNOVER_PENALTY",
    "MIN_EXECUTION_SCORE",
    "MIN_LONG_TERM_SCAN_SCORE",
    "MIN_REWARD_RISK",
    "MIN_SHORT_TERM_SCAN_SCORE",
    "StrategyPreset",
    "LOGGABLE_SOURCE_QUALITIES",
    "LOGGABLE_TRADE_STATES",
    "LONG_TERM_HORIZON_DAYS",
    "LOW_SAMPLE_RESOLVED_THRESHOLD",
    "PERFORMANCE_DB_FILE",
    "PERFORMANCE_MODEL_VERSION",
    "PORTFOLIO_HISTORY_MIN_SNAPSHOT_MINUTES",
    "RESEARCH_EXECUTION_LOG_FILE",
    "RESEARCH_LOG_DIR",
    "RESEARCH_LOGGING_ENABLED",
    "REWARD_RISK_FILTER_ENABLED",
    "SLIPPAGE_BPS",
    "STRATEGY_PRESETS",
    "STRATEGY_V1",
    "SIGNAL_DEDUPE_ENTRY_MOVE_THRESHOLD_PCT",
    "SIGNAL_DEDUPE_LOOKBACK_DAYS",
    "SKIPPED_SOURCE_QUALITIES",
    "SQLITE_TIMEOUT_SECONDS",
    "SUPPORTED_LONG_TERM_STRATEGIES",
    "SUPPORTED_SIGNAL_STRATEGIES",
    "SWING_TRADE_HOLDING_DAYS",
    "TIME_STOP_ENABLED",
    "TIME_STOP_MAX_HOLDING_DAYS",
    "TIME_STOP_MIN_FAVORABLE_MOVE_PCT",
    "TURNOVER_LOOKBACK_DAYS",
    "get_strategy_preset",
    "estimated_round_trip_cost_pct",
    "performance_assumptions_snapshot",
    "sample_quality_label",
]
