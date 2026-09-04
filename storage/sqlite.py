from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from config.performance import PERFORMANCE_DB_FILE, SQLITE_TIMEOUT_SECONDS


SIGNALS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    company_name TEXT,
    strategy_family TEXT NOT NULL,
    signal_origin TEXT NOT NULL,
    source_quality TEXT NOT NULL,
    model_version TEXT NOT NULL,

    recommendation_label TEXT NOT NULL,
    recommendation_confidence TEXT NOT NULL,
    trade_state TEXT,
    holding_period_label TEXT,

    score REAL NOT NULL,
    entry_price REAL,
    target_price REAL,
    stop_loss_price REAL,

    trend_direction TEXT,
    setup_type TEXT,
    invalidation_note TEXT,

    accounting_quality_score REAL,
    shenanigan_risk_score REAL,
    accounting_data_completeness_score REAL,
    accounting_assessment_confidence TEXT,

    news_score REAL,
    news_impact REAL,

    feature_snapshot_json TEXT NOT NULL,
    evaluated INTEGER NOT NULL DEFAULT 0
);
"""


SIGNAL_OUTCOMES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    outcome_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    resolution_reason TEXT NOT NULL,

    evaluation_window_bars INTEGER,
    evaluation_window_days INTEGER,

    entry_price REAL,
    exit_price REAL,
    target_price REAL,
    stop_loss_price REAL,

    max_favorable_excursion_pct REAL,
    max_adverse_excursion_pct REAL,
    realized_return_pct REAL,
    holding_days REAL,

    first_target_hit_at TEXT,
    first_stop_hit_at TEXT,

    FOREIGN KEY(signal_id) REFERENCES signals(signal_id)
);
"""


PORTFOLIO_HISTORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_history_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_name TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    deployed_capital_weight REAL NOT NULL,
    cash_reserve_weight REAL NOT NULL,
    realized_pnl_pct REAL,
    unrealized_pnl_pct REAL,
    total_portfolio_pnl_pct REAL,
    weighted_hit_rate REAL,
    holdings_count INTEGER NOT NULL,
    open_holdings_count INTEGER NOT NULL,
    resolved_holdings_count INTEGER NOT NULL,
    equal_weight_baseline_pnl_pct REAL,
    immediate_entry_baseline_pnl_pct REAL
);
"""


STRATEGY_HISTORY_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS strategy_history_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    snapshot_at TEXT NOT NULL,
    triggered_signals_count INTEGER NOT NULL,
    waiting_signals_count INTEGER NOT NULL,
    eligible_signals_count INTEGER NOT NULL,
    cohort_expectancy_pct REAL,
    cohort_win_rate REAL,
    average_edge_score REAL,
    average_position_size REAL,
    average_risk_penalty REAL
);
"""


INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_signals_ticker_created_at
ON signals (ticker, created_at);

CREATE INDEX IF NOT EXISTS idx_signals_strategy_created_at
ON signals (strategy_family, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_dedupe_key
ON signals (dedupe_key);

CREATE INDEX IF NOT EXISTS idx_signals_evaluated_strategy
ON signals (evaluated, strategy_family, created_at);

CREATE INDEX IF NOT EXISTS idx_outcomes_signal_id
ON signal_outcomes (signal_id);

CREATE INDEX IF NOT EXISTS idx_outcomes_status
ON signal_outcomes (status);

CREATE INDEX IF NOT EXISTS idx_portfolio_history_name_time
ON portfolio_history_snapshots (portfolio_name, snapshot_at);

CREATE INDEX IF NOT EXISTS idx_strategy_history_name_time
ON strategy_history_snapshots (strategy_name, snapshot_at);
"""


BOOTSTRAP_SQL = "\n".join(
    [
        SIGNALS_TABLE_DDL.strip(),
        SIGNAL_OUTCOMES_TABLE_DDL.strip(),
        PORTFOLIO_HISTORY_TABLE_DDL.strip(),
        STRATEGY_HISTORY_TABLE_DDL.strip(),
        INDEX_DDL.strip(),
    ]
)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    resolved_path = db_path or PERFORMANCE_DB_FILE
    _ensure_parent(resolved_path)
    connection = sqlite3.connect(
        resolved_path,
        timeout=SQLITE_TIMEOUT_SECONDS,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    connection.execute("PRAGMA journal_mode = WAL;")
    connection.execute("PRAGMA synchronous = NORMAL;")
    return connection


_bootstrapped_paths: set[str] = set()


def initialize_database(db_path: Path | None = None) -> None:
    with get_connection(db_path) as connection:
        connection.executescript(BOOTSTRAP_SQL)
        connection.commit()


def bootstrap_database(db_path: Path | None = None) -> None:
    """Idempotent app-startup hook that ensures the SQLite schema exists.

    Call this once from the application entry point (`app.py`) before any
    repository is constructed or any service runs. Subsequent calls with the
    same `db_path` are no-ops, so this is safe to invoke from multiple paths
    (CLI scripts, test fixtures, the Streamlit launcher) without paying the
    cost of re-running DDL on every repository instantiation.
    """
    resolved = db_path or PERFORMANCE_DB_FILE
    key = str(Path(resolved).resolve())
    if key in _bootstrapped_paths:
        return

    if Path(resolved).resolve() == PERFORMANCE_DB_FILE.resolve():
        from storage.seed import seed_runtime_data

        seed_runtime_data(Path(resolved))
    initialize_database(resolved)
    _bootstrapped_paths.add(key)


def init_db(db_path: Path | None = None) -> None:
    initialize_database(db_path)


def ensure_schema(db_path: Path | None = None) -> None:
    """Backwards-compatible alias for `bootstrap_database`.

    Repository classes used to call this from their `__init__`; that has been
    centralised. Keep this thin shim so any external caller still works.
    """
    bootstrap_database(db_path)


@contextmanager
def connection_scope(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    connection = get_connection(db_path)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


__all__ = [
    "BOOTSTRAP_SQL",
    "INDEX_DDL",
    "PORTFOLIO_HISTORY_TABLE_DDL",
    "SIGNALS_TABLE_DDL",
    "SIGNAL_OUTCOMES_TABLE_DDL",
    "STRATEGY_HISTORY_TABLE_DDL",
    "bootstrap_database",
    "connection_scope",
    "ensure_schema",
    "get_connection",
    "init_db",
    "initialize_database",
]
