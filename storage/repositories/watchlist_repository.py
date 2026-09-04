from __future__ import annotations

from config.settings import WATCHLIST_FILE
from storage.cache.json_cache import load_json, save_json


def load_watchlist() -> list[dict[str, str]]:
    return load_json(WATCHLIST_FILE, [])


def add_to_watchlist(ticker: str, source: str) -> None:
    normalized = ticker.upper().strip()
    watchlist = load_watchlist()
    if any(item["ticker"] == normalized for item in watchlist):
        return
    watchlist.append({"ticker": normalized, "source": source})
    save_json(WATCHLIST_FILE, watchlist)


def remove_from_watchlist(ticker: str) -> None:
    normalized = ticker.upper().strip()
    watchlist = [item for item in load_watchlist() if item["ticker"] != normalized]
    save_json(WATCHLIST_FILE, watchlist)
