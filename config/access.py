from __future__ import annotations

import os
from typing import Literal, TypedDict


WRITE_MODE_ENV = "OMNITRADE_WRITE_MODE"
READ_ONLY_WRITE_MODE = "read_only"
LOCAL_WRITE_MODE = "local"
WriteMode = Literal["read_only", "local"]


class ApiCapabilities(TypedDict):
    write_mode: WriteMode
    user_mutations_enabled: bool
    performance_log_mutations_enabled: bool
    watchlist_mutations_enabled: bool
    message: str


def api_write_mode(value: str | None = None) -> WriteMode:
    """Return the explicit API write mode, failing closed for missing or invalid values."""

    raw_value = os.environ.get(WRITE_MODE_ENV, "") if value is None else value
    normalized = raw_value.strip().lower()
    return LOCAL_WRITE_MODE if normalized == LOCAL_WRITE_MODE else READ_ONLY_WRITE_MODE


def api_capabilities_snapshot(value: str | None = None) -> ApiCapabilities:
    mode = api_write_mode(value)
    mutations_enabled = mode == LOCAL_WRITE_MODE
    return {
        "write_mode": mode,
        "user_mutations_enabled": mutations_enabled,
        "performance_log_mutations_enabled": mutations_enabled,
        "watchlist_mutations_enabled": mutations_enabled,
        "message": (
            "Local write mode is enabled."
            if mutations_enabled
            else "This deployment is read-only. Run OmniTrade locally to modify performance records or the watchlist."
        ),
    }


__all__ = [
    "ApiCapabilities",
    "LOCAL_WRITE_MODE",
    "READ_ONLY_WRITE_MODE",
    "WRITE_MODE_ENV",
    "api_capabilities_snapshot",
    "api_write_mode",
]
