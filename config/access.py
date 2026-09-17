from __future__ import annotations

import os
from typing import Literal, TypedDict


WRITE_MODE_ENV = "OMNITRADE_WRITE_MODE"
ADMIN_MODE_ENV = "OMNITRADE_ADMIN"
READ_ONLY_WRITE_MODE = "read_only"
LOCAL_WRITE_MODE = "local"
WriteMode = Literal["read_only", "local"]


class ApiCapabilities(TypedDict):
    write_mode: WriteMode
    user_mutations_enabled: bool
    performance_log_mutations_enabled: bool
    watchlist_mutations_enabled: bool
    admin_access_enabled: bool
    message: str


def is_admin_access_enabled(value: str | None = None) -> bool:
    """Return whether admin-only validation and lab areas are visible.
    
    Defaults to true in local write mode or when OMNITRADE_ADMIN is explicitly '1'/'true'.
    In read_only mode (e.g. public hosted web), defaults to false so validation areas
    remain hidden from general users unless explicitly configured as admin.
    """
    raw_admin = os.environ.get(ADMIN_MODE_ENV, "") if value is None else value
    normalized_admin = raw_admin.strip().lower()
    if normalized_admin in {"1", "true", "yes", "enabled"}:
        return True
    if normalized_admin in {"0", "false", "no", "disabled"}:
        return False
    # If not explicitly set, local write mode grants admin access; hosted read_only does not.
    return api_write_mode() == LOCAL_WRITE_MODE


def api_write_mode(value: str | None = None) -> WriteMode:
    """Return the explicit API write mode, failing closed for missing or invalid values."""

    raw_value = os.environ.get(WRITE_MODE_ENV, "") if value is None else value
    normalized = raw_value.strip().lower()
    return LOCAL_WRITE_MODE if normalized == LOCAL_WRITE_MODE else READ_ONLY_WRITE_MODE


def api_capabilities_snapshot(value: str | None = None) -> ApiCapabilities:
    mode = api_write_mode(value)
    mutations_enabled = mode == LOCAL_WRITE_MODE
    admin_enabled = is_admin_access_enabled()
    return {
        "write_mode": mode,
        "user_mutations_enabled": mutations_enabled,
        "performance_log_mutations_enabled": mutations_enabled,
        "watchlist_mutations_enabled": mutations_enabled,
        "admin_access_enabled": admin_enabled,
        "message": (
            "Local write mode is enabled."
            if mutations_enabled
            else "This deployment is read-only. Run OmniTrade locally to modify performance records or the watchlist."
        ),
    }


__all__ = [
    "ADMIN_MODE_ENV",
    "ApiCapabilities",
    "LOCAL_WRITE_MODE",
    "READ_ONLY_WRITE_MODE",
    "WRITE_MODE_ENV",
    "api_capabilities_snapshot",
    "api_write_mode",
    "is_admin_access_enabled",
]
