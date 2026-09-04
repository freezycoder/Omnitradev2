from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import LATEST_VIEW_SCAN_FILE, REAL_SCAN_CACHE_FILE, SCAN_CACHE_DIR
from storage.cache.json_cache import load_json, save_json


def _scan_cache_path(cache_key: str) -> Path:
    normalized = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in cache_key)
    return SCAN_CACHE_DIR / f"{normalized}.json"


def load_latest_view_scan() -> dict[str, Any] | None:
    return load_json(LATEST_VIEW_SCAN_FILE, None)


def save_latest_view_scan(payload: dict[str, Any]) -> None:
    save_json(LATEST_VIEW_SCAN_FILE, payload)


def load_real_scan_cache() -> dict[str, Any] | None:
    return load_json(REAL_SCAN_CACHE_FILE, None)


def save_real_scan_cache(payload: dict[str, Any]) -> None:
    save_json(REAL_SCAN_CACHE_FILE, payload)


def load_named_scan_cache(cache_key: str) -> dict[str, Any] | None:
    if cache_key == "default":
        return load_real_scan_cache()
    return load_json(_scan_cache_path(cache_key), None)


def save_named_scan_cache(cache_key: str, payload: dict[str, Any]) -> None:
    if cache_key == "default":
        save_real_scan_cache(payload)
        return
    save_json(_scan_cache_path(cache_key), payload)
