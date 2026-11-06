from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row

from domain.portfolio.book_analysis import BookHolding, parse_holdings


class OperatorBookRepository(Protocol):
    def load(self) -> tuple[BookHolding, ...]: ...

    def save(self, holdings: tuple[BookHolding, ...]) -> None: ...

    @property
    def store_name(self) -> str: ...


class JsonOperatorBookRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def store_name(self) -> str:
        return "file"

    def load(self) -> tuple[BookHolding, ...]:
        from storage.cache.json_cache import load_json

        payload = load_json(self.path, [])
        if not isinstance(payload, list):
            return ()
        rows = [item for item in payload if isinstance(item, dict)]
        return parse_holdings(rows) if rows else ()

    def save(self, holdings: tuple[BookHolding, ...]) -> None:
        from storage.cache.json_cache import save_json

        save_json(
            self.path,
            [{"ticker": holding.ticker, "weight_pct": holding.weight_pct} for holding in holdings],
        )


class PostgresOperatorBookRepository:
    """Holdings live next to the alert ledger so the weekly job can read them."""

    def __init__(self, database_url: str, *, connect: Callable[[], Any] | None = None) -> None:
        if not database_url.strip():
            raise ValueError("OMNITRADE_ALERT_DATABASE_URL is required")
        self.database_url = database_url
        self._connect_override = connect
        if connect is None:
            self._ensure_schema()

    @property
    def store_name(self) -> str:
        return "postgres"

    def load(self) -> tuple[BookHolding, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ticker, weight_pct FROM operator_holdings ORDER BY ticker"
            ).fetchall()
        if not rows:
            return ()
        return parse_holdings(rows)

    def save(self, holdings: tuple[BookHolding, ...]) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("DELETE FROM operator_holdings")
            for holding in holdings:
                conn.execute(
                    """
                    INSERT INTO operator_holdings (ticker, weight_pct, updated_at)
                    VALUES (%s, %s, %s)
                    """,
                    (holding.ticker, holding.weight_pct, updated_at),
                )

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS operator_holdings (
                    ticker TEXT PRIMARY KEY,
                    weight_pct DOUBLE PRECISION NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> Any:
        if self._connect_override is not None:
            return self._connect_override()
        return psycopg.connect(self.database_url, row_factory=dict_row)


def open_operator_book(database_url: str, *, path: Path | None = None) -> OperatorBookRepository:
    from config.settings import OPERATOR_BOOK_FILE

    if database_url.strip():
        return PostgresOperatorBookRepository(database_url)
    return JsonOperatorBookRepository(path or OPERATOR_BOOK_FILE)
