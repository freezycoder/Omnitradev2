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


def test_etf_regions_endpoint_lists_listing_universes():
    payload = asyncio.run(main.etf_regions())
    keys = {item["key"] for item in payload["regions"]}
    assert payload["default"] == "us"
    assert keys == {"us", "europe", "asia_pacific"}
    europe = next(item for item in payload["regions"] if item["key"] == "europe")
    assert europe["ticker_count"] > 0
    assert "UCITS" in europe["label"]


def test_etf_analysis_accepts_exchange_suffix(monkeypatch):
    monkeypatch.setattr(
        "application.etf_service.EtfService.build_analysis",
        lambda self, ticker, refresh=False: {
            "asset_type": "ETF",
            "ticker": ticker,
            "profile": EtfProfile(ticker=ticker, name="Vanguard FTSE All-World").to_dict(),
            "metrics": {"current_price": 100.0},
            "holdings": None,
        },
    )

    payload = asyncio.run(main.etf_analysis("vwce.de"))
    assert payload["ticker"] == "VWCE.DE"
