from __future__ import annotations

import gzip
import sqlite3
from pathlib import Path

import storage.seed as seed_module


def _write_seed_database(path: Path, *, ticker: str = "AAPL") -> None:
    source = path.with_suffix(".source.db")
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE signals (ticker TEXT NOT NULL)")
        connection.execute("INSERT INTO signals (ticker) VALUES (?)", (ticker,))
    with source.open("rb") as raw, gzip.open(path, "wb") as compressed:
        compressed.write(raw.read())


def test_seed_runtime_data_hydrates_empty_database_and_caches(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    data_dir = tmp_path / "runtime"
    seed_dir.mkdir()
    database_seed = seed_dir / "omnitrade.db.gz"
    _write_seed_database(database_seed)

    cache_seed = seed_dir / "global.json"
    cache_seed.write_text('{"source":"live"}', encoding="utf-8")
    cache_target = data_dir / "scan_cache" / "global.json"

    monkeypatch.setattr(seed_module, "DATABASE_SEED_FILE", database_seed)
    monkeypatch.setattr(seed_module, "SEEDED_CACHE_FILES", ((cache_seed, cache_target),))

    database_seeded, caches_seeded = seed_module.seed_runtime_data(data_dir / "omnitrade.db")

    assert database_seeded is True
    assert caches_seeded == 1
    with sqlite3.connect(data_dir / "omnitrade.db") as connection:
        assert connection.execute("SELECT ticker FROM signals").fetchone() == ("AAPL",)
    assert cache_target.read_text(encoding="utf-8") == '{"source":"live"}'


def test_seed_runtime_data_preserves_existing_runtime_data(tmp_path, monkeypatch):
    seed_dir = tmp_path / "seed"
    data_dir = tmp_path / "runtime"
    seed_dir.mkdir()
    database_seed = seed_dir / "omnitrade.db.gz"
    _write_seed_database(database_seed, ticker="AAPL")

    runtime_database = data_dir / "omnitrade.db"
    runtime_database.parent.mkdir()
    with sqlite3.connect(runtime_database) as connection:
        connection.execute("CREATE TABLE signals (ticker TEXT NOT NULL)")
        connection.execute("INSERT INTO signals (ticker) VALUES ('MSFT')")

    monkeypatch.setattr(seed_module, "DATABASE_SEED_FILE", database_seed)
    monkeypatch.setattr(seed_module, "SEEDED_CACHE_FILES", ())

    database_seeded, caches_seeded = seed_module.seed_runtime_data(runtime_database)

    assert database_seeded is False
    assert caches_seeded == 0
    with sqlite3.connect(runtime_database) as connection:
        assert connection.execute("SELECT ticker FROM signals").fetchone() == ("MSFT",)


def test_seed_runtime_data_replaces_demo_cache_with_real_cache(tmp_path, monkeypatch):
    data_dir = tmp_path / "runtime"
    source = tmp_path / "global.json"
    target = data_dir / "scan_cache" / "global.json"
    source.write_text('{"source":"live","updated_at":"2026-06-10"}', encoding="utf-8")
    target.parent.mkdir(parents=True)
    target.write_text('{"source":"demo","updated_at":"2026-06-22"}', encoding="utf-8")

    monkeypatch.setattr(seed_module, "DATABASE_SEED_FILE", tmp_path / "missing.db.gz")
    monkeypatch.setattr(seed_module, "SEEDED_CACHE_FILES", ((source, target),))

    database_seeded, caches_seeded = seed_module.seed_runtime_data(data_dir / "omnitrade.db")

    assert database_seeded is False
    assert caches_seeded == 1
    assert target.read_text(encoding="utf-8") == '{"source":"live","updated_at":"2026-06-10"}'
