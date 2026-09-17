from __future__ import annotations

import json
from datetime import date

from config.kcroro_regime import (
    HY_OAS_SERIES_ID,
    KCRORO_SERIES_ID,
    NFCI_SERIES_ID,
    RELEASE_LAG_CALENDAR_DAYS,
)
from providers.macro import kcroro_client


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_kcroro_client_collapses_vintages_to_first_release_date(monkeypatch):
    client = kcroro_client.KcroroClient(
        api_key="test",
        allow_public_csv=False,
        include_keep_comparators=False,
        include_subindexes=False,
    )

    def fake_urlopen(request, timeout):
        url = str(request.full_url)
        assert "realtime_start=1776-07-04" in url
        payload = {
            "observations": [
                {
                    "date": "2026-09-08",
                    "realtime_start": "2026-09-09",
                    "realtime_end": "9999-12-31",
                    "value": "0.1814",
                },
                {
                    "date": "2026-09-08",
                    "realtime_start": "2026-09-10",
                    "realtime_end": "9999-12-31",
                    "value": "0.1900",
                },
                {
                    "date": "2026-09-07",
                    "realtime_start": "2026-09-08",
                    "realtime_end": "9999-12-31",
                    "value": "-0.2100",
                },
            ]
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(kcroro_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_kcroro()
    assert source == "fred_alfred_initial_release"
    by_day = {row.observation_date: row for row in rows}
    assert by_day[date(2026, 9, 8)].release_date == date(2026, 9, 9)
    assert by_day[date(2026, 9, 8)].kcroro == 0.1814
    assert by_day[date(2026, 9, 7)].release_date == date(2026, 9, 8)


def test_kcroro_client_falls_back_to_frozen_release_lag_without_vintages(monkeypatch):
    client = kcroro_client.KcroroClient(
        api_key="test",
        allow_public_csv=False,
        include_keep_comparators=False,
        include_subindexes=False,
    )

    def fake_urlopen(request, timeout):
        url = str(request.full_url)
        if "realtime_start" in url:
            raise kcroro_client.URLError("vintage window unavailable")
        payload = {
            "observations": [
                {"date": "2026-09-08", "value": "0.1814"},
            ]
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(kcroro_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_kcroro()
    assert source == "fred_api_release_lag"
    assert rows[0].observation_date == date(2026, 9, 8)
    assert rows[0].release_date == date(2026, 9, 9)
    assert rows[0].kcroro == 0.1814
    assert RELEASE_LAG_CALENDAR_DAYS == 1


def test_public_csv_fallback_uses_release_lag(monkeypatch):
    client = kcroro_client.KcroroClient(
        api_key="",
        allow_public_csv=True,
        include_keep_comparators=False,
        include_subindexes=False,
    )
    csv_text = "observation_date,KCRORO\n2026-09-08,0.1814\n"

    def fake_urlopen(request, timeout):
        return _FakeResponse(csv_text.encode("utf-8"))

    monkeypatch.setattr(kcroro_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_kcroro()
    assert source == "fred_public_csv_release_lag"
    assert rows[0].release_date == date(2026, 9, 9)
    assert KCRORO_SERIES_ID == "KCRORO"
    assert HY_OAS_SERIES_ID == "BAMLH0A0HYM2"
    assert NFCI_SERIES_ID == "NFCI"
