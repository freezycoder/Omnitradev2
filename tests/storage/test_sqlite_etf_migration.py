from __future__ import annotations

import sqlite3

from storage.sqlite import initialize_database


def test_initialize_database_adds_asset_type_without_destroying_existing_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE signals (
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
                score REAL NOT NULL,
                feature_snapshot_json TEXT NOT NULL,
                evaluated INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            INSERT INTO signals (
                signal_id, dedupe_key, created_at, ticker, company_name, strategy_family,
                signal_origin, source_quality, model_version, recommendation_label,
                recommendation_confidence, score, feature_snapshot_json, evaluated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sig-1",
                "dedupe-1",
                "2026-01-01T00:00:00+00:00",
                "AAPL",
                "Apple",
                "short_term_swing",
                "scanner",
                "live",
                "v1",
                "Watchlist",
                "Moderate",
                70,
                "{}",
                0,
            ),
        )

    initialize_database(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(signals)")}
        ticker, asset_type = connection.execute("SELECT ticker, asset_type FROM signals").fetchone()
        etf_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('etfs', 'etf_holdings', 'etf_holdings_snapshots')"
            )
        }

    assert "asset_type" in columns
    assert ticker == "AAPL"
    assert asset_type == "STOCK"
    assert etf_tables == {"etfs", "etf_holdings", "etf_holdings_snapshots"}
