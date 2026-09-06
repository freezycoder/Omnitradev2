from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from fastapi import HTTPException

from api import main


def test_overview_auto_cold_start_uses_demo_seed(monkeypatch):
    import application.scan_service as scan_service
    import storage.repositories.scan_repository as scan_repository

    calls: dict[str, Any] = {}

    def fake_run_scan(*, universe, data_mode, universe_name, cache_key):
        calls.update(
            {
                "universe": universe,
                "data_mode": data_mode,
                "universe_name": universe_name,
                "cache_key": cache_key,
            }
        )
        return {
            "source": data_mode,
            "universe_name": universe_name,
            "universe": universe,
            "market_stats": {},
            "long_term": [],
            "short_term": [],
            "market_rows": [],
            "failures": [],
        }

    monkeypatch.setattr(scan_repository, "load_named_scan_cache", lambda cache_key: None)
    monkeypatch.setattr(scan_repository, "load_latest_view_scan", lambda: None)
    monkeypatch.setattr(scan_service, "run_scan", fake_run_scan)

    payload = main._load_overview_payload(
        refresh=False,
        data_mode=main.DATA_MODE_AUTO,
        universe_key="global",
    )

    assert calls["data_mode"] == main.DATA_MODE_DEMO
    assert calls["cache_key"] == "global"
    assert payload["source"] == main.DATA_MODE_DEMO
    assert "No cached scan" in payload["api_note"]


def test_overview_auto_ignores_cache_missing_new_universe_tickers(monkeypatch):
    import application.scan_service as scan_service
    import storage.repositories.scan_repository as scan_repository

    calls: dict[str, Any] = {}
    old_cache = {
        "source": "live",
        "universe_name": "Global Liquid Leaders",
        "universe": ["AAPL", "MSFT"],
        "market_stats": {},
        "long_term": [],
        "short_term": [],
        "market_rows": [],
        "failures": [],
    }

    def fake_run_scan(*, universe, data_mode, universe_name, cache_key):
        calls.update({"data_mode": data_mode, "cache_key": cache_key, "universe": universe})
        return {
            "source": data_mode,
            "universe_name": universe_name,
            "universe": universe,
            "market_stats": {},
            "long_term": [],
            "short_term": [],
            "market_rows": [],
            "failures": [],
        }

    monkeypatch.setattr(scan_repository, "load_named_scan_cache", lambda cache_key: old_cache)
    monkeypatch.setattr(scan_repository, "load_latest_view_scan", lambda: None)
    monkeypatch.setattr(scan_service, "run_scan", fake_run_scan)

    payload = main._load_overview_payload(
        refresh=False,
        data_mode=main.DATA_MODE_AUTO,
        universe_key="global",
    )

    assert calls["data_mode"] == main.DATA_MODE_DEMO
    assert "SPCX" in calls["universe"]
    assert payload["source"] == main.DATA_MODE_DEMO


def test_overview_auto_accepts_high_coverage_real_cache(monkeypatch):
    import storage.repositories.scan_repository as scan_repository

    current_universe = main._overview_universe_config("global")["tickers"]
    cached_universe = [ticker for ticker in current_universe if ticker not in {"BE", "PSKY", "QBTS", "SNDK", "SPCX"}]
    cached = {
        "source": "live",
        "updated_at": datetime.now(UTC).isoformat(),
        "universe_name": "Global Liquid Leaders",
        "universe": cached_universe,
        "market_stats": {},
        "long_term": [{"ticker": "AAPL"}],
        "short_term": [{"ticker": "MSFT", "trade_state": "ENTER NOW", "is_actionable_now": True}],
        "market_rows": [],
        "failures": [],
    }

    monkeypatch.setattr(scan_repository, "load_named_scan_cache", lambda cache_key: cached)
    monkeypatch.setattr(scan_repository, "load_latest_view_scan", lambda: None)

    payload = main._load_overview_payload(
        refresh=False,
        data_mode=main.DATA_MODE_AUTO,
        universe_key="global",
    )

    assert payload["source"] == "cached_real"
    assert payload["data_status"]["status"] == "fresh"
    assert payload["data_status"]["is_actionable"] is True
    assert "34 of 39" in payload["api_note"]
    assert "SPCX" in payload["api_note"]


def test_overview_timeout_fallback_prefers_cache(monkeypatch):
    import storage.repositories.scan_repository as scan_repository

    cached = {
        "source": "live",
        "updated_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
        "universe_name": "Global Liquid Leaders",
        "universe": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "AMD", "NFLX", "ORCL", "CRM", "JPM", "V", "LLY", "ABBV", "UNH", "XOM", "COST", "WMT", "UBER", "TSM", "ASML", "NVO", "SHEL", "SAP", "BABA", "SONY", "TM", "RY", "SHOP", "MELI", "PDD", "UL", "RELX", "SPCX", "PSKY", "SNDK", "QBTS", "BE"],
        "market_stats": {},
        "long_term": [],
        "short_term": [
            {
                "ticker": "AAPL",
                "trade_state": "ENTER NOW",
                "is_actionable_now": True,
                "entry_price": 100.0,
                "target_price": 110.0,
                "stop_loss_price": 95.0,
            }
        ],
        "market_rows": [],
        "failures": [],
    }

    monkeypatch.setattr(scan_repository, "load_named_scan_cache", lambda cache_key: cached)
    monkeypatch.setattr(scan_repository, "load_latest_view_scan", lambda: None)

    payload = main._load_overview_fallback_payload(
        universe_key="global",
        reason="The live overview scan timed out.",
    )

    assert payload["source"] == "cached_real"
    assert payload["data_status"]["status"] == "stale"
    assert payload["data_status"]["is_actionable"] is False
    assert payload["short_term"][0]["trade_state"] == "STALE — REFRESH REQUIRED"
    assert payload["short_term"][0]["entry_price"] is None
    assert "timed out" in payload["api_note"]
    assert "cached scan" in payload["api_note"]


def test_overview_route_uses_fallback_on_timeout(monkeypatch):
    calls: list[str] = []

    async def fake_run_service(name, fn, **kwargs):
        calls.append(name)
        if name == "overview":
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "service_timeout",
                    "service": name,
                    "message": "overview did not finish within 90 seconds.",
                },
            )
        return fn()

    monkeypatch.setattr(main, "_run_service", fake_run_service)
    monkeypatch.setattr(
        main,
        "_load_overview_fallback_payload",
        lambda *, universe_key, reason: {"source": "demo", "api_note": reason},
    )

    from tests.api.request_helpers import fake_request

    payload = asyncio.run(
        main.overview(
            fake_request(),
            refresh=True,
            data_mode=main.DATA_MODE_AUTO,
            universe="global",
        )
    )

    assert calls == ["overview", "overview_fallback"]
    assert payload["source"] == "demo"
    assert "timed out" in payload["api_note"]


def test_overview_refresh_deduplicates_an_active_scan(monkeypatch):
    import application.scan_service as scan_service

    scan_started = Event()
    finish_scan = Event()
    calls = 0
    first_payload: dict[str, Any] = {}

    def fake_run_scan(*, universe, data_mode, universe_name, cache_key):
        nonlocal calls
        calls += 1
        scan_started.set()
        assert finish_scan.wait(timeout=2)
        return {
            "source": data_mode,
            "updated_at": datetime.now(UTC).isoformat(),
            "universe_name": universe_name,
            "universe": universe,
            "market_stats": {},
            "long_term": [],
            "short_term": [],
            "market_rows": [],
            "failures": [],
        }

    monkeypatch.setattr(scan_service, "run_scan", fake_run_scan)
    monkeypatch.setattr(
        main,
        "_load_overview_fallback_payload",
        lambda *, universe_key, reason: {
            "source": "cached_real",
            "updated_at": "2026-07-13T20:00:00+00:00",
            "api_note": reason,
        },
    )

    def run_first_refresh():
        first_payload.update(
            main._load_overview_payload(
                refresh=True,
                data_mode=main.DATA_MODE_AUTO,
                universe_key="global",
            )
        )

    first_refresh = Thread(target=run_first_refresh)
    first_refresh.start()
    assert scan_started.wait(timeout=2)

    duplicate_payload = main._load_overview_payload(
        refresh=True,
        data_mode=main.DATA_MODE_AUTO,
        universe_key="global",
    )

    assert calls == 1
    assert duplicate_payload["source"] == "cached_real"
    assert duplicate_payload["refresh_status"] == "running"
    assert "already running" in duplicate_payload["api_note"]

    finish_scan.set()
    first_refresh.join(timeout=2)
    assert not first_refresh.is_alive()
    assert first_payload["source"] == "cached_real"
    assert first_payload["refresh_status"] == "running"

    final_status: dict[str, Any] = {}
    for _ in range(40):
        final_status = main._load_overview_refresh_status(universe_key="global")
        if final_status["refresh_status"] == "complete":
            break
        Event().wait(0.05)

    assert final_status["refresh_status"] == "complete"
    assert final_status["source"] == main.DATA_MODE_AUTO
