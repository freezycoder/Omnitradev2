from __future__ import annotations

from pathlib import Path
from typing import Any

from config.settings import TICKER_CACHE_DIR
from storage.cache.json_cache import load_json, save_json


def _ticker_cache_path(ticker: str) -> Path:
    return TICKER_CACHE_DIR / f"{ticker.upper().strip()}.json"


def load_cached_ticker_data(ticker: str) -> dict[str, Any] | None:
    return load_json(_ticker_cache_path(ticker), None)


def save_cached_ticker_data(ticker: str, payload: dict[str, Any]) -> None:
    save_json(_ticker_cache_path(ticker), payload)
