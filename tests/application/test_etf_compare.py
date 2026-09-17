from __future__ import annotations

import pytest

from application.etf_service import EtfService
from domain.etf.models import EtfProfile


def test_compare_treats_provider_errors_as_missing(monkeypatch):
    def boom(self, ticker, refresh=False):
        raise RuntimeError("HTTP Error 404: Not Found")

    monkeypatch.setattr(EtfService, "build_analysis", boom)

    with pytest.raises(ValueError, match="At least two valid ETFs"):
        EtfService().compare(["AAA", "BBB"])


def test_compare_skips_none_analysis_and_requires_two_valid(monkeypatch):
    monkeypatch.setattr(EtfService, "build_analysis", lambda self, ticker, refresh=False: None)

    with pytest.raises(ValueError, match="two or more"):
        EtfService().compare(["SPY"])

    with pytest.raises(ValueError, match="At least two valid ETFs"):
        EtfService().compare(["SPY", "QQQ"])


def test_compare_returns_payload_for_two_valid_etfs(monkeypatch):
    def fake_analysis(self, ticker, refresh=False):
        profile = EtfProfile(ticker=ticker, name=f"{ticker} Fund", quote_type="ETF")
        return {
            "ticker": ticker,
            "profile": profile.to_dict(),
            "metrics": {},
            "omni_score": {"score": 50.0},
            "history": [],
            "holdings": None,
        }

    monkeypatch.setattr(EtfService, "build_analysis", fake_analysis)
    payload = EtfService().compare(["QQQ", "SPY"])

    assert {item["ticker"] for item in payload["etfs"]} == {"QQQ", "SPY"}
    assert payload["pairs"]
