from __future__ import annotations

import pytest

from config.access import (
    ADMIN_MODE_ENV,
    ADMIN_PASSWORD_ENV,
    DEFAULT_ADMIN_PASSWORD,
    LOCAL_WRITE_MODE,
    READ_ONLY_WRITE_MODE,
    api_capabilities_snapshot,
    api_write_mode,
    get_admin_password,
    is_admin_access_enabled,
    is_admin_password_valid,
)


@pytest.mark.parametrize("value", [None, "", "production", "enabled", "LOCAL_ONLY", "invalid"])
def test_api_write_mode_fails_closed(value, monkeypatch):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)

    assert api_write_mode(value) == READ_ONLY_WRITE_MODE


@pytest.mark.parametrize("value", ["local", "LOCAL", " local "])
def test_api_write_mode_accepts_explicit_local_mode(value):
    assert api_write_mode(value) == LOCAL_WRITE_MODE


def test_read_only_capabilities_disable_all_user_mutations(monkeypatch):
    monkeypatch.delenv(ADMIN_MODE_ENV, raising=False)
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)
    capabilities = api_capabilities_snapshot("read_only")

    assert capabilities["user_mutations_enabled"] is False
    assert capabilities["performance_log_mutations_enabled"] is False
    assert capabilities["watchlist_mutations_enabled"] is False
    assert capabilities["admin_access_enabled"] is False
    assert "read-only" in capabilities["message"]


def test_local_capabilities_enable_all_user_mutations(monkeypatch):
    monkeypatch.delenv(ADMIN_MODE_ENV, raising=False)
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "local")
    capabilities = api_capabilities_snapshot("local")

    assert capabilities["user_mutations_enabled"] is True
    assert capabilities["performance_log_mutations_enabled"] is True
    assert capabilities["watchlist_mutations_enabled"] is True
    assert capabilities["admin_access_enabled"] is True


def test_admin_mode_can_be_explicitly_configured(monkeypatch):
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "read_only")
    monkeypatch.setenv(ADMIN_MODE_ENV, "1")
    assert is_admin_access_enabled() is True
    assert api_capabilities_snapshot()["admin_access_enabled"] is True

    monkeypatch.setenv(ADMIN_MODE_ENV, "false")
    assert is_admin_access_enabled() is False
    assert api_capabilities_snapshot()["admin_access_enabled"] is False


def test_admin_password_validation(monkeypatch):
    monkeypatch.delenv(ADMIN_PASSWORD_ENV, raising=False)
    assert get_admin_password() == "7180"
    assert is_admin_password_valid("7180") is True
    assert is_admin_password_valid("wrong") is False
    assert is_admin_password_valid(None) is False

    # Custom password via environment
    monkeypatch.setenv(ADMIN_PASSWORD_ENV, "custom_secret")
    assert get_admin_password() == "custom_secret"
    assert is_admin_password_valid("custom_secret") is True
    assert is_admin_password_valid("7180") is False


def test_read_only_mode_allows_admin_access_with_valid_password(monkeypatch):
    monkeypatch.delenv(ADMIN_MODE_ENV, raising=False)
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "read_only")

    # Without password, read_only defaults to False
    assert is_admin_access_enabled() is False
    assert api_capabilities_snapshot()["admin_access_enabled"] is False

    # With correct password 7180, access is granted
    assert is_admin_access_enabled(password="7180") is True
    assert api_capabilities_snapshot(password="7180")["admin_access_enabled"] is True

    # With incorrect password, access is denied
    assert is_admin_access_enabled(password="1234") is False
    assert api_capabilities_snapshot(password="1234")["admin_access_enabled"] is False
