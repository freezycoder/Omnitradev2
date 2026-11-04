from __future__ import annotations

from domain.portfolio.book_analysis import BookHolding
from storage.repositories.operator_book_repository import (
    JsonOperatorBookRepository,
    PostgresOperatorBookRepository,
)


def test_json_book_round_trip(tmp_path) -> None:
    repo = JsonOperatorBookRepository(tmp_path / "book.json")
    repo.save((BookHolding("AAPL", 12.5), BookHolding("NVDA", 7)))
    assert repo.load() == (BookHolding("AAPL", 12.5), BookHolding("NVDA", 7.0))
    assert repo.store_name == "file"


def test_postgres_book_replaces_the_saved_rows() -> None:
    conn = FakeConnection(rows=[{"ticker": "MSFT", "weight_pct": 15}])
    repo = PostgresOperatorBookRepository("postgresql://db.example/omnitrade", connect=lambda: conn)

    repo.save((BookHolding("AAPL", 20),))
    loaded = repo.load()

    assert loaded == (BookHolding("MSFT", 15.0),)
    assert any("DELETE FROM operator_holdings" in sql for sql, _params in conn.calls)
    assert any("INSERT INTO operator_holdings" in sql for sql, _params in conn.calls)


class FakeConnection:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, object]] = []

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def execute(self, sql: str, params=None):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return self.rows
