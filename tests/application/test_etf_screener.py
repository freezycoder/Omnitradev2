from __future__ import annotations

import time
from threading import Event

import pytest

from application.etf_service import EtfService
from domain.etf.models import EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile
from storage.repositories.etf_repository import EtfRepository
from storage.sqlite import initialize_database


class FakeEtfProvider:
    name = "fake"

    def __init__(self) -> None:
        self.profile_calls: list[str] = []
        self.holdings_calls: list[str] = []
        self.profiles = {
            "QQQ": EtfProfile(ticker="QQQ", name="Invesco QQQ Trust", issuer="Invesco", quote_type="ETF"),
            "SPY": EtfProfile(ticker="SPY", name="SPDR S&P 500", issuer="SSGA", quote_type="ETF"),
        }

    def get_profile(self, ticker: str) -> EtfProfile | None:
        self.profile_calls.append(ticker.upper())
        return self.profiles.get(ticker.upper())

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        self.holdings_calls.append(ticker.upper())
        return None

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        return []

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        return EtfFlowSnapshot(ticker=ticker.upper(), available=False, unavailable_reason="Flows are not published.")

    def search(self, query: str) -> list[EtfProfile]:
        profile = self.get_profile(query)
        return [profile] if profile else []


def test_screener_without_refresh_does_not_hit_provider(tmp_path, monkeypatch):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    provider = FakeEtfProvider()
    monkeypatch.setattr("application.etf_service.load_named_scan_cache", lambda key: None)
    service = EtfService(repository=EtfRepository(db_path), provider=provider)

    payload = service.build_screener(refresh=False)

    assert payload["rows"] == []
    assert provider.profile_calls == []
    assert "Refresh cache" in payload["api_note"]


def test_screener_refresh_does_not_scrape_holdings(tmp_path, monkeypatch):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    provider = FakeEtfProvider()
    saved: dict[str, object] = {}
    monkeypatch.setattr("application.etf_service.DEFAULT_ETF_UNIVERSE", ["QQQ", "SPY"])
    monkeypatch.setattr("application.etf_service.fetch_price_histories", lambda tickers, period="2y": {})
    monkeypatch.setattr("application.etf_service.load_stock_signal_scores", lambda: {})
    monkeypatch.setattr("application.etf_service.save_named_scan_cache", lambda key, payload: saved.update(payload))
    service = EtfService(repository=EtfRepository(db_path), provider=provider)

    payload = service.build_screener(refresh=True)

    assert {row["ticker"] for row in payload["rows"]} == {"QQQ", "SPY"}
    assert provider.holdings_calls == []
    assert saved["partial"] is False
    assert len(saved["rows"]) == 2


def test_etf_screener_get_does_not_start_live_job(monkeypatch):
    from api import main

    started: list[str] = []
    monkeypatch.setattr(main, "_start_etf_refresh_job", lambda: started.append("start") or {})
    monkeypatch.setattr(
        "application.etf_service.EtfService.cached_screener",
        lambda self, filters=None: None,
    )

    payload = main._load_etf_screener_payload(refresh=False, filters=None)

    assert started == []
    assert payload["rows"] == []
    assert payload["refresh_status"] == "idle"


def test_etf_screener_refresh_starts_background_job(monkeypatch):
    from api import main

    scan_started = Event()
    finish_scan = Event()

    def fake_build(self, filters=None, *, refresh=False, log_signals=False):
        scan_started.set()
        assert finish_scan.wait(timeout=2)
        return {
            "updated_at": "2026-09-12T21:00:00+00:00",
            "source": "live",
            "rows": [{"ticker": "QQQ"}],
        }

    monkeypatch.setattr("application.etf_service.EtfService.build_screener", fake_build)
    monkeypatch.setattr("application.etf_service.EtfService.cached_screener", lambda self, filters=None: None)

    main._ETF_REFRESH_JOB = None
    if main._ETF_REFRESH_LOCK.locked():
        main._ETF_REFRESH_LOCK.release()

    payload = main._load_etf_screener_payload(refresh=True, filters=None)
    assert payload["refresh_status"] == "running"
    assert scan_started.wait(timeout=2)

    second = main._load_etf_screener_payload(refresh=True, filters=None)
    assert second["refresh_job"]["already_running"] is True

    finish_scan.set()
    for _ in range(50):
        if not main._ETF_REFRESH_LOCK.locked():
            break
        time.sleep(0.05)
    else:
        pytest.fail("ETF refresh worker did not release the lock")
