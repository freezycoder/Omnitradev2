from __future__ import annotations

from fastapi.testclient import TestClient

from api.security import public_error_message
from tests.api.request_helpers import fake_request


def test_public_error_message_redacts_exceptions_in_production():
    assert public_error_message(RuntimeError("secret path /tmp/key"), environment="production") == (
        "The service failed. See server logs for details."
    )
    assert "secret path" in public_error_message(RuntimeError("secret path /tmp/key"), environment="development")


def test_api_sets_security_headers_and_trims_root_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    from api import main

    client = TestClient(main.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in response.headers["content-security-policy"]
    if main.is_production():
        root = client.get("/")
        assert "docs_url" not in root.json()
        assert "frontend_url" not in root.json()
        assert client.get("/docs").status_code == 404


def test_write_token_is_required_when_configured(monkeypatch):
    monkeypatch.setenv("OMNITRADE_WRITE_MODE", "local")
    monkeypatch.setenv("OMNITRADE_WRITE_TOKEN", "correct-token")
    from api.main import WatchlistMutation, add_watchlist_item

    from fastapi import HTTPException

    try:
        add_watchlist_item(WatchlistMutation(ticker="AAPL"), fake_request())
        raise AssertionError("expected missing token to fail")
    except HTTPException as exc:
        assert exc.status_code == 401

    try:
        add_watchlist_item(
            WatchlistMutation(ticker="AAPL"),
            fake_request(headers={"x-omnitrade-write-token": "wrong-token"}),
        )
        raise AssertionError("expected wrong token to fail")
    except HTTPException as exc:
        assert exc.status_code == 401


def test_watchlist_rejects_tampered_fields():
    from pydantic import ValidationError

    from api.main import PerformanceLogMutation, WatchlistMutation

    try:
        WatchlistMutation(ticker="AAPL;DROP TABLE", source="frontend")
        raise AssertionError("expected invalid ticker")
    except ValidationError:
        pass

    try:
        WatchlistMutation(ticker="AAPL", source="<script>")
        raise AssertionError("expected invalid source")
    except ValidationError:
        pass

    try:
        PerformanceLogMutation(
            ticker="AAPL",
            strategy_family="short_term_swing",
            opened_on="2026-01-01",
            closed_on="2026-01-02",
            score=10,
            entry_price=1,
            exit_price=2,
            status="not_a_real_status",
        )
        raise AssertionError("expected invalid status")
    except ValidationError:
        pass


def test_refresh_rate_limit_blocks_bursts(monkeypatch):
    monkeypatch.setenv("ENV", "development")
    from api.security import enforce_rate_limit
    from fastapi import HTTPException

    request = fake_request(host="203.0.113.9")
    for _ in range(6):
        enforce_rate_limit(request, bucket="refresh-test", limit=6)
    try:
        enforce_rate_limit(request, bucket="refresh-test", limit=6)
        raise AssertionError("expected rate limit")
    except HTTPException as exc:
        assert exc.status_code == 429
