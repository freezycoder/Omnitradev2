from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api import main


PERFORMANCE_LOG_PAYLOAD = {
    "ticker": "AAPL",
    "strategy_family": "short_term_swing",
    "opened_on": "2026-07-20",
    "closed_on": "2026-07-21",
    "score": 72,
    "entry_price": 100,
    "exit_price": 104,
    "status": "hit_target",
}


@pytest.mark.parametrize(
    "operation",
    [
        "performance_log",
        "watchlist_add",
        "watchlist_delete",
    ],
)
def test_user_mutations_are_blocked_by_default(monkeypatch, operation):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        if operation == "performance_log":
            asyncio.run(main.performance_log(main.PerformanceLogMutation(**PERFORMANCE_LOG_PAYLOAD)))
        elif operation == "watchlist_add":
            main.add_watchlist_item(main.WatchlistMutation(ticker="AAPL"))
        else:
            main.delete_watchlist_item("AAPL")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "error": "read_only_deployment",
        "operation": operation,
        "message": (
            "This deployment is read-only. Run OmniTrade locally to modify performance records or the watchlist."
        ),
    }


def test_capabilities_endpoint_reports_read_only_by_default(monkeypatch):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)
    monkeypatch.delenv("OMNITRADE_ADMIN", raising=False)

    payload = main.api_capabilities()

    assert payload["write_mode"] == "read_only"
    assert payload["user_mutations_enabled"] is False
    assert payload["admin_access_enabled"] is False


@pytest.mark.parametrize(
    "endpoint",
    [
        "calibration",
        "performance_lab",
        "long_term_performance",
    ],
)
def test_validation_endpoints_require_admin_in_read_only_mode(monkeypatch, endpoint):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)
    monkeypatch.delenv("OMNITRADE_ADMIN", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        if endpoint == "calibration":
            asyncio.run(main.calibration())
        elif endpoint == "performance_lab":
            asyncio.run(main.performance_lab())
        else:
            asyncio.run(main.long_term_performance())

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["error"] == "admin_access_required"
    assert "restricted to administrators" in exc_info.value.detail["message"]


@pytest.mark.parametrize(
    "endpoint",
    [
        "calibration",
        "performance_lab",
        "long_term_performance",
    ],
)
def test_validation_endpoints_allow_access_with_admin_password_header(monkeypatch, endpoint):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)
    monkeypatch.delenv("OMNITRADE_ADMIN", raising=False)

    ran = []
    async def fake_run_service(name, fn, **kw):
        ran.append(name)
        return {"status": "ok"}

    monkeypatch.setattr(main, "_run_service", fake_run_service)

    # Calling with valid password header 7180 succeeds
    if endpoint == "calibration":
        asyncio.run(main.calibration(x_admin_password="7180"))
    elif endpoint == "performance_lab":
        asyncio.run(main.performance_lab(price_mode="cached", x_admin_password="7180"))
    else:
        asyncio.run(main.long_term_performance(x_admin_password="7180"))

    assert endpoint in ran


def test_capabilities_unlocks_with_admin_password_header(monkeypatch):
    monkeypatch.delenv("OMNITRADE_WRITE_MODE", raising=False)
    monkeypatch.delenv("OMNITRADE_ADMIN", raising=False)

    locked = main.api_capabilities()
    assert locked["admin_access_enabled"] is False

    unlocked = main.api_capabilities(x_admin_password="7180")
    assert unlocked["admin_access_enabled"] is True


def test_admin_verify_endpoint():
    # Valid password returns success
    res = main.admin_verify(main.AdminVerifyRequest(password="7180"))
    assert res["status"] == "ok"
    assert res["admin_access_enabled"] is True

    # Invalid password raises 401
    with pytest.raises(HTTPException) as exc_info:
        main.admin_verify(main.AdminVerifyRequest(password="bad"))
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["error"] == "invalid_admin_password"


def test_validation_endpoints_accessible_in_local_admin_mode(monkeypatch):
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "local")
    monkeypatch.setenv("OMNITRADE_ADMIN", "1")

    ran = []
    async def fake_run_service(name, fn, **kw):
        ran.append(name)
        return {"status": "ok"}

    monkeypatch.setattr(main, "_run_service", fake_run_service)
    asyncio.run(main.calibration())
    assert "calibration" in ran


def test_cors_allows_only_declared_methods_without_credentials():
    middleware = next(
        item for item in main.app.user_middleware if item.cls is CORSMiddleware
    )

    assert middleware.kwargs["allow_credentials"] is False
    assert middleware.kwargs["allow_methods"] == ["GET", "POST", "DELETE"]
    assert "Content-Type" in middleware.kwargs["allow_headers"]
    assert "x-admin-password" in middleware.kwargs["allow_headers"]


def test_production_cors_does_not_enable_private_network_regex_by_default(monkeypatch):
    monkeypatch.delenv("OMNITRADE_CORS_ORIGIN_REGEX", raising=False)

    assert main._cors_origin_regex(environment="production") is None
    assert main._cors_origin_regex(environment="development") == main.PRIVATE_NETWORK_ORIGIN_REGEX
    assert main._cors_origin_regex(environment="production", configured_regex=r"^https://app\.example$") == (
        r"^https://app\.example$"
    )


def test_local_mode_allows_watchlist_mutation(monkeypatch):
    import storage.repositories.watchlist_repository as watchlist_repository

    added: list[tuple[str, str]] = []
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "local")
    monkeypatch.setattr(
        watchlist_repository,
        "add_to_watchlist",
        lambda ticker, source: added.append((ticker, source)),
    )
    monkeypatch.setattr(
        main,
        "_watchlist_payload",
        lambda: [{"ticker": "AAPL", "source": "test"}],
    )

    response = main.add_watchlist_item(main.WatchlistMutation(ticker="aapl", source="test"))

    assert added == [("AAPL", "test")]
    assert response["watchlist"] == [{"ticker": "AAPL", "source": "test"}]


def test_local_mode_allows_performance_log_mutation(monkeypatch):
    captured: list[Any] = []
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "local")

    def fake_log(payload):
        captured.append(payload)
        return {
            "status": "ok",
            "entry": {
                "ticker": payload.ticker,
                "realized_return_pct": 4.0,
            },
        }

    monkeypatch.setattr(main, "_log_performance_entry", fake_log)

    response = asyncio.run(main.performance_log(main.PerformanceLogMutation(**PERFORMANCE_LOG_PAYLOAD)))

    assert len(captured) == 1
    assert response["entry"]["ticker"] == "AAPL"
