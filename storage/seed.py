from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
from pathlib import Path

from config.settings import BASE_DIR, DATA_DIR


SEED_DIR = BASE_DIR / "seed_data"
DATABASE_SEED_FILE = SEED_DIR / "omnitrade.db.gz"

SEEDED_CACHE_FILES = (
    (SEED_DIR / "latest_real_scan.json", DATA_DIR / "latest_real_scan.json"),
    (SEED_DIR / "latest_scan_results.json", DATA_DIR / "latest_scan_results.json"),
    (SEED_DIR / "scan_cache" / "global.json", DATA_DIR / "scan_cache" / "global.json"),
    (SEED_DIR / "scan_cache" / "international.json", DATA_DIR / "scan_cache" / "international.json"),
)


def _database_has_signals(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False

    try:
        with sqlite3.connect(path) as connection:
            row = connection.execute("SELECT 1 FROM signals LIMIT 1").fetchone()
    except sqlite3.DatabaseError:
        return False
    return row is not None


def _seed_database(target: Path) -> bool:
    if _database_has_signals(target) or not DATABASE_SEED_FILE.exists():
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.seed.tmp")
    try:
        with gzip.open(DATABASE_SEED_FILE, "rb") as source, temporary.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _seed_caches() -> int:
    copied = 0
    for source, target in SEEDED_CACHE_FILES:
        if not source.exists() or not _cache_should_seed(source, target):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied


def _cache_should_seed(source: Path, target: Path) -> bool:
    if not target.exists():
        return True

    try:
        source_payload = json.loads(source.read_text(encoding="utf-8"))
        target_payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    real_sources = {"live", "cached_real"}
    return source_payload.get("source") in real_sources and target_payload.get("source") not in real_sources


def seed_runtime_data(db_path: Path | None = None) -> tuple[bool, int]:
    """Hydrate an empty runtime with the bundled AI history and scan caches."""
    database_seeded = _seed_database(Path(db_path or DATA_DIR / "omnitrade.db"))
    caches_seeded = _seed_caches()
    return database_seeded, caches_seeded


__all__ = ["seed_runtime_data"]
