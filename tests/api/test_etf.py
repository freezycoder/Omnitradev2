from __future__ import annotations

import asyncio

from fastapi import HTTPException

from api import main
from domain.etf.models import EtfProfile


def test_etf_analysis_endpoint_returns_payload(monkeypatch):
    monkeypatch.setattr(
        "application.etf_service.EtfService.build_analysis",
        lambda self, ticker, refresh=False: {
            "asset_type": "ETF",
            "ticker": ticker,
            "profile": EtfProfile(ticker=ticker, name="Test ETF").to_dict(),
            "metrics": {"current_price": 100.0},
            "holdings": None,
        },
    )

    payload = asyncio.run(main.etf_analysis("qqq"))

    assert payload["ticker"] == "QQQ"
    assert payload["asset_type"] == "ETF"
    assert payload["holdings"] is None


def test_etf_analysis_404_when_missing(monkeypatch):
    monkeypatch.setattr("application.etf_service.EtfService.build_analysis", lambda self, ticker, refresh=False: None)
    try:
        asyncio.run(main.etf_analysis("ZZZZ"))
        raise AssertionError("expected 404")
    except HTTPException as exc:
        assert exc.status_code == 404


def test_etf_compare_one_symbol_is_400():
    try:
        asyncio.run(main.etf_compare("SPY"))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"] == "invalid_compare"


def test_etf_compare_valueerror_inside_service_is_400(monkeypatch):
    def boom(self, tickers):
        raise ValueError("At least two valid ETFs are required for comparison.")

    monkeypatch.setattr("application.etf_service.EtfService.compare", boom)
    try:
        asyncio.run(main.etf_compare("SPY,QQQ"))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "At least two valid ETFs" in exc.detail["message"]


def test_etf_compare_provider_404_is_400(monkeypatch):
    def boom(self, tickers):
        raise Exception("HTTP Error 404: Not Found")

    monkeypatch.setattr("application.etf_service.EtfService.compare", boom)
    try:
        asyncio.run(main.etf_compare("ZZZZ,YYYY"))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"] == "invalid_compare"


def test_etf_screener_timeout_falls_back_to_cache(monkeypatch):
    async def fake_run_service(name, fn, **kwargs):
        if name == "etf_screener":
            raise HTTPException(
                status_code=504,
                detail={"error": "service_timeout", "service": name, "message": "timed out"},
            )
        return fn()

    monkeypatch.setattr(main, "_run_service", fake_run_service)
    monkeypatch.setattr(
        "application.etf_service.EtfService.cached_screener",
        lambda self, filters=None: {"rows": [{"ticker": "SPY"}], "universe_name": "cached"},
    )

    payload = asyncio.run(main.etf_screener(refresh=True))
    assert payload["rows"][0]["ticker"] == "SPY"
    assert "timed out" in payload["api_note"].lower()


def test_etf_screener_timeout_without_cache_stays_504(monkeypatch):
    async def fake_run_service(name, fn, **kwargs):
        raise HTTPException(
            status_code=504,
            detail={"error": "service_timeout", "service": name, "message": "timed out"},
        )

    monkeypatch.setattr(main, "_run_service", fake_run_service)
    monkeypatch.setattr("application.etf_service.EtfService.cached_screener", lambda self, filters=None: None)

    try:
        asyncio.run(main.etf_screener(refresh=True))
        raise AssertionError("expected 504")
    except HTTPException as exc:
        assert exc.status_code == 504
