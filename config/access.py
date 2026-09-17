from __future__ import annotations

import hmac
import os
from typing import Literal, TypedDict


WRITE_MODE_ENV = "OMNITRADE_WRITE_MODE"
ADMIN_MODE_ENV = "OMNITRADE_ADMIN"
ADMIN_PASSWORD_ENV = "OMNITRADE_ADMIN_PASSWORD"
DEFAULT_ADMIN_PASSWORD = "7180"

READ_ONLY_WRITE_MODE = "read_only"
LOCAL_WRITE_MODE = "local"
WriteMode = Literal["read_only", "local"]


class ApiCapabilities(TypedDict, total=False):
    write_mode: WriteMode
    user_mutations_enabled: bool
    performance_log_mutations_enabled: bool
    watchlist_mutations_enabled: bool
    admin_access_enabled: bool
    admin_password_required: bool
    message: str


def get_admin_password() -> str:
    """Return the configured administrator password, defaulting to 7180."""
    return os.environ.get(ADMIN_PASSWORD_ENV, DEFAULT_ADMIN_PASSWORD).strip()


def is_admin_password_valid(candidate: str | None) -> bool:
    """Check if candidate password matches the configured admin password."""
    if candidate is None:
        return False
    expected = get_admin_password()
    return hmac.compare_digest(str(candidate).strip(), expected)


def is_admin_access_enabled(value: str | None = None, password: str | None = None) -> bool:
    """Return whether admin-only validation and lab areas are visible.
    
    If password is provided as a non-empty string, checks against the configured admin password (default 7180).
    Otherwise checks OMNITRADE_ADMIN environment variable ('1'/'true'/'yes'/'enabled').
    If OMNITRADE_ADMIN is '0'/'false'/'no'/'disabled', returns False unless a valid password is supplied.
    If not explicitly configured, defaults to True in local write mode for convenience,
    or False in read_only mode (hosted).
    """
    if password is not None and not isinstance(password, str):
        # Handle cases where default argument is a FastAPI Header object
        password = None
    if password:
        return is_admin_password_valid(password)
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


def api_capabilities_snapshot(value: str | None = None, password: str | None = None) -> ApiCapabilities:
    mode = api_write_mode(value)
    mutations_enabled = mode == LOCAL_WRITE_MODE
    admin_enabled = is_admin_access_enabled(password=password)
    return {
        "write_mode": mode,
        "user_mutations_enabled": mutations_enabled,
        "performance_log_mutations_enabled": mutations_enabled,
        "watchlist_mutations_enabled": mutations_enabled,
        "admin_access_enabled": admin_enabled,
        "admin_password_required": True,
        "message": (
            "Local write mode is enabled."
            if mutations_enabled
            else "This deployment is read-only. Run OmniTrade locally to modify performance records or the watchlist."
        ),
    }


__all__ = [
    "ADMIN_MODE_ENV",
    "ADMIN_PASSWORD_ENV",
    "ApiCapabilities",
    "DEFAULT_ADMIN_PASSWORD",
    "LOCAL_WRITE_MODE",
    "READ_ONLY_WRITE_MODE",
    "WRITE_MODE_ENV",
    "api_capabilities_snapshot",
    "api_write_mode",
    "get_admin_password",
    "is_admin_access_enabled",
    "is_admin_password_valid",
]
