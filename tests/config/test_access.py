from __future__ import annotations

import pytest

from config.access import (
    LOCAL_WRITE_MODE,
    READ_ONLY_WRITE_MODE,
    api_capabilities_snapshot,
    api_write_mode,
)


@pytest.mark.parametrize("value", [None, "", "production", "enabled", "LOCAL_ONLY", "invalid"])
def test_api_write_mode_fails_closed(value, monkeypatch):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)

    assert api_write_mode(value) == READ_ONLY_WRITE_MODE


@pytest.mark.parametrize("value", ["local", "LOCAL", " local "])
def test_api_write_mode_accepts_explicit_local_mode(value):
    assert api_write_mode(value) == LOCAL_WRITE_MODE


def test_read_only_capabilities_disable_all_user_mutations():
    capabilities = api_capabilities_snapshot("read_only")

    assert capabilities["user_mutations_enabled"] is False
    assert capabilities["performance_log_mutations_enabled"] is False
    assert capabilities["watchlist_mutations_enabled"] is False
    assert "read-only" in capabilities["message"]


def test_local_capabilities_enable_all_user_mutations():
    capabilities = api_capabilities_snapshot("local")

    assert capabilities["user_mutations_enabled"] is True
    assert capabilities["performance_log_mutations_enabled"] is True
    assert capabilities["watchlist_mutations_enabled"] is True
