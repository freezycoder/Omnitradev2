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


def test_etf_compare_requires_two_symbols():
    try:
        asyncio.run(main.etf_compare("SPY"))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"] == "invalid_compare"
        assert "two or more" in exc.detail["message"].lower()


def test_etf_compare_maps_service_valueerror_to_400(monkeypatch):
    def boom(self, tickers):
        raise ValueError("At least two valid ETFs are required for comparison.")

    monkeypatch.setattr("application.etf_service.EtfService.compare", boom)
    try:
        asyncio.run(main.etf_compare("ZZZZ,YYYY"))
        raise AssertionError("expected 400")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert exc.detail["error"] == "invalid_compare"
        assert "two valid" in exc.detail["message"].lower()
