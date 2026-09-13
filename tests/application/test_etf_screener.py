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
            "VWCE.DE": EtfProfile(ticker="VWCE.DE", name="Vanguard FTSE All-World", issuer="Vanguard", quote_type="ETF"),
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
    monkeypatch.setattr("application.etf_service.universe_for", lambda region=None: ["QQQ", "SPY"])
    monkeypatch.setattr("application.etf_service.fetch_price_histories", lambda tickers, period="2y": {})
    monkeypatch.setattr("application.etf_service.load_stock_signal_scores", lambda: {})
    monkeypatch.setattr("application.etf_service.save_named_scan_cache", lambda key, payload: saved.update(payload) or saved.setdefault("cache_key", key))
    service = EtfService(repository=EtfRepository(db_path), provider=provider)

    payload = service.build_screener(refresh=True)

    assert {row["ticker"] for row in payload["rows"]} == {"QQQ", "SPY"}
    assert provider.holdings_calls == []
    assert saved["partial"] is False
    assert saved["cache_key"] == "etf_us"
    assert len(saved["rows"]) == 2
    assert payload["region"] == "us"


def test_screener_refresh_saves_europe_cache_separately(tmp_path, monkeypatch):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    provider = FakeEtfProvider()
    saved: list[tuple[str, dict]] = []
    monkeypatch.setattr("application.etf_service.universe_for", lambda region=None: ["VWCE.DE"])
    monkeypatch.setattr("application.etf_service.fetch_price_histories", lambda tickers, period="2y": {})
    monkeypatch.setattr("application.etf_service.load_stock_signal_scores", lambda: {})
    monkeypatch.setattr("application.etf_service.save_named_scan_cache", lambda key, payload: saved.append((key, payload)))
    service = EtfService(repository=EtfRepository(db_path), provider=provider)

    payload = service.build_screener(refresh=True, region="europe")

    assert payload["region"] == "europe"
    assert {row["ticker"] for row in payload["rows"]} == {"VWCE.DE"}
    assert saved[-1][0] == "etf_europe"
    assert "SPY" not in {row["ticker"] for row in payload["rows"]}


def test_cached_screener_does_not_mix_regions(monkeypatch, tmp_path):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)
    loaded: list[str] = []

    def fake_load(key):
        loaded.append(key)
        if key == "etf_europe":
            return {"rows": [{"ticker": "VWCE.DE"}], "universe": ["VWCE.DE"]}
        if key == "etf_us":
            return {"rows": [{"ticker": "SPY"}], "universe": ["SPY"]}
        return None

    monkeypatch.setattr("application.etf_service.load_named_scan_cache", fake_load)
    service = EtfService(repository=EtfRepository(db_path), provider=FakeEtfProvider())

    europe = service.cached_screener(region="europe")
    us = service.cached_screener(region="us")

    assert europe["rows"][0]["ticker"] == "VWCE.DE"
    assert us["rows"][0]["ticker"] == "SPY"
    assert loaded == ["etf_europe", "etf_us"]


def test_us_region_falls_back_to_legacy_etf_cache(monkeypatch, tmp_path):
    db_path = tmp_path / "etf.db"
    initialize_database(db_path)

    def fake_load(key):
        if key == "etf_us":
            return None
        if key == "etf":
            return {"rows": [{"ticker": "QQQ"}], "universe": ["QQQ"]}
        return None

    monkeypatch.setattr("application.etf_service.load_named_scan_cache", fake_load)
    service = EtfService(repository=EtfRepository(db_path), provider=FakeEtfProvider())

    payload = service.cached_screener(region="us")
    assert payload["rows"][0]["ticker"] == "QQQ"
    assert payload["region"] == "us"


def test_etf_screener_get_does_not_start_live_job(monkeypatch):
    from api import main

    started: list[str] = []
    monkeypatch.setattr(main, "_start_etf_refresh_job", lambda region="us": started.append(region) or {})
    monkeypatch.setattr(
        "application.etf_service.EtfService.cached_screener",
        lambda self, filters=None, region="us": None,
    )

    payload = main._load_etf_screener_payload(refresh=False, filters=None, region="europe")

    assert started == []
    assert payload["rows"] == []
    assert payload["region"] == "europe"
    assert payload["refresh_status"] == "idle"


def test_load_payload_does_not_mix_regions(monkeypatch):
    from api import main

    def fake_cached(self, filters=None, region="us"):
        if region == "europe":
            return {"rows": [{"ticker": "VWCE.DE"}], "region": "europe"}
        return {"rows": [{"ticker": "SPY"}], "region": "us"}

    monkeypatch.setattr("application.etf_service.EtfService.cached_screener", fake_cached)

    us = main._load_etf_screener_payload(refresh=False, filters=None, region="us")
    europe = main._load_etf_screener_payload(refresh=False, filters=None, region="europe")

    assert us["rows"][0]["ticker"] == "SPY"
    assert europe["rows"][0]["ticker"] == "VWCE.DE"


def test_etf_screener_refresh_starts_background_job(monkeypatch):
    from api import main

    scan_started = Event()
    finish_scan = Event()
    regions_seen: list[str] = []

    def fake_build(self, filters=None, *, refresh=False, log_signals=False, region="us"):
        regions_seen.append(region)
        scan_started.set()
        assert finish_scan.wait(timeout=2)
        return {
            "updated_at": "2026-09-12T21:00:00+00:00",
            "source": "live",
            "rows": [{"ticker": "VWCE.DE"}],
            "region": region,
        }

    monkeypatch.setattr("application.etf_service.EtfService.build_screener", fake_build)
    monkeypatch.setattr(
        "application.etf_service.EtfService.cached_screener",
        lambda self, filters=None, region="us": None,
    )

    main._ETF_REFRESH_JOBS.clear()
    lock = main._etf_region_lock("europe")
    if lock.locked():
        lock.release()

    payload = main._load_etf_screener_payload(refresh=True, filters=None, region="europe")
    assert payload["refresh_status"] == "running"
    assert payload["region"] == "europe"
    assert scan_started.wait(timeout=2)

    second = main._load_etf_screener_payload(refresh=True, filters=None, region="europe")
    assert second["refresh_job"]["already_running"] is True

    finish_scan.set()
    for _ in range(50):
        if not lock.locked():
            break
        time.sleep(0.05)
    else:
        pytest.fail("ETF refresh worker did not release the lock")
    assert regions_seen == ["europe"]


def test_etf_refresh_jobs_are_isolated_per_region(monkeypatch):
    from api import main

    us_started = Event()
    europe_started = Event()
    finish = Event()

    def fake_build(self, filters=None, *, refresh=False, log_signals=False, region="us"):
        if region == "us":
            us_started.set()
        else:
            europe_started.set()
        assert finish.wait(timeout=2)
        return {"rows": [], "region": region, "updated_at": "2026-09-12T21:00:00+00:00", "source": "live"}

    monkeypatch.setattr("application.etf_service.EtfService.build_screener", fake_build)
    monkeypatch.setattr(
        "application.etf_service.EtfService.cached_screener",
        lambda self, filters=None, region="us": None,
    )
    main._ETF_REFRESH_JOBS.clear()
    for region in ("us", "europe"):
        lock = main._etf_region_lock(region)
        if lock.locked():
            lock.release()

    us_payload = main._load_etf_screener_payload(refresh=True, filters=None, region="us")
    europe_payload = main._load_etf_screener_payload(refresh=True, filters=None, region="europe")

    assert us_payload["refresh_job"]["already_running"] is False
    assert europe_payload["refresh_job"]["already_running"] is False
    assert us_started.wait(timeout=2)
    assert europe_started.wait(timeout=2)

    finish.set()
    for region in ("us", "europe"):
        lock = main._etf_region_lock(region)
        for _ in range(50):
            if not lock.locked():
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"{region} refresh worker did not release the lock")
