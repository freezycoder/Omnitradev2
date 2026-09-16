from __future__ import annotations

import json
from datetime import date
from io import BytesIO

from config.nfci_regime import HY_OAS_SERIES_ID, NFCI_SERIES_ID
from providers.macro import nfci_client


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_nfci_client_collapses_vintages_to_first_release_date(monkeypatch):
    client = nfci_client.NfciClient(api_key="test", allow_public_csv=False, include_hy_keep=False)

    def fake_urlopen(request, timeout):
        url = str(request.full_url)
        assert "realtime_start=1776-07-04" in url
        payload = {
            "observations": [
                {
                    "date": "2026-09-04",
                    "realtime_start": "2026-09-10",
                    "realtime_end": "9999-12-31",
                    "value": "-0.564",
                },
                {
                    "date": "2026-09-04",
                    "realtime_start": "2026-09-17",
                    "realtime_end": "9999-12-31",
                    "value": "-0.580",
                },
                {
                    "date": "2026-08-28",
                    "realtime_start": "2026-09-03",
                    "realtime_end": "9999-12-31",
                    "value": "-0.500",
                },
            ]
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(nfci_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_nfci()
    assert source == "fred_alfred_initial_release"
    by_week = {row.observation_week_end: row for row in rows}
    assert by_week[date(2026, 9, 4)].release_date == date(2026, 9, 10)
    assert by_week[date(2026, 9, 4)].nfci == -0.564
    assert by_week[date(2026, 8, 28)].release_date == date(2026, 9, 3)


def test_nfci_client_falls_back_to_frozen_release_lag_without_vintages(monkeypatch):
    client = nfci_client.NfciClient(api_key="test", allow_public_csv=False, include_hy_keep=False)

    def fake_urlopen(request, timeout):
        url = str(request.full_url)
        if "realtime_start" in url:
            raise nfci_client.URLError("vintage window unavailable")
        payload = {
            "observations": [
                {"date": "2026-09-04", "value": "-0.564"},
            ]
        }
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(nfci_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_nfci()
    assert source == "fred_api_release_lag"
    assert rows[0].observation_week_end == date(2026, 9, 4)
    assert rows[0].release_date == date(2026, 9, 10)


def test_public_csv_fallback_uses_release_lag(monkeypatch):
    client = nfci_client.NfciClient(api_key="", allow_public_csv=True, include_hy_keep=False)
    csv_text = "observation_date,NFCI\n2026-09-04,-0.564\n"

    def fake_urlopen(request, timeout):
        return _FakeResponse(csv_text.encode("utf-8"))

    monkeypatch.setattr(nfci_client, "urlopen", fake_urlopen)
    rows, source = client._fetch_nfci()
    assert source == "fred_public_csv_release_lag"
    assert rows[0].release_date == date(2026, 9, 10)
    assert NFCI_SERIES_ID == "NFCI"
    assert HY_OAS_SERIES_ID == "BAMLH0A0HYM2"
