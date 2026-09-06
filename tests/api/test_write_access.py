from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api import main
from tests.api.request_helpers import fake_request


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
            asyncio.run(
                main.performance_log(main.PerformanceLogMutation(**PERFORMANCE_LOG_PAYLOAD), fake_request())
            )
        elif operation == "watchlist_add":
            main.add_watchlist_item(main.WatchlistMutation(ticker="AAPL"), fake_request())
        else:
            main.delete_watchlist_item("AAPL", fake_request())

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

    payload = main.api_capabilities()

    assert payload["write_mode"] == "read_only"
    assert payload["user_mutations_enabled"] is False


def test_cors_allows_only_declared_methods_without_credentials():
    middleware = next(
        item for item in main.app.user_middleware if item.cls is CORSMiddleware
    )

    assert middleware.kwargs["allow_credentials"] is False
    assert middleware.kwargs["allow_methods"] == ["GET", "POST", "DELETE"]
    assert middleware.kwargs["allow_headers"] == ["Content-Type", "X-OmniTrade-Write-Token"]


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

    response = main.add_watchlist_item(main.WatchlistMutation(ticker="aapl", source="test"), fake_request())

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

    response = asyncio.run(
        main.performance_log(main.PerformanceLogMutation(**PERFORMANCE_LOG_PAYLOAD), fake_request())
    )

    assert len(captured) == 1
    assert response["entry"]["ticker"] == "AAPL"
