from __future__ import annotations

import gzip
import json
from datetime import date, timedelta

import pytest

from config.stfm_funding_liquidity import (
    DAILY_RELEASE_LAG_CALENDAR_DAYS,
    FROZEN_MNEMONICS,
    MMF_RELEASE_LAG_CALENDAR_DAYS,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_MMF_TOTAL,
)
from providers.macro import ofr_stfm_client
from providers.macro.ofr_stfm_client import OfrStfmClient


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_client_refuses_unfrozen_mnemonics():
    client = OfrStfmClient(api_key="", allow_public_csv=False, include_keep_comparators=False)
    with pytest.raises(ValueError, match="frozen STFM mnemonic set"):
        client.fetch_mnemonic("REPO-DVP_TV_TOT-F")


def test_timeseries_preserves_nulls_and_applies_daily_release_lag(monkeypatch):
    client = OfrStfmClient(api_key="", allow_public_csv=False, include_keep_comparators=False)
    payload = [
        ["2026-09-14", 1.0],
        ["2026-09-15", None],
        ["2026-09-16", 2.0],
    ]

    def fake_urlopen(request, timeout):
        assert MNEMONIC_DVP_VOLUME in str(request.full_url)
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(ofr_stfm_client, "urlopen", fake_urlopen)
    rows = client.fetch_mnemonic(MNEMONIC_DVP_VOLUME)
    by_obs = {row.observation_date: row for row in rows}
    assert by_obs[date(2026, 9, 15)].value is None
    assert by_obs[date(2026, 9, 15)].release_date == date(2026, 9, 15) + timedelta(
        days=DAILY_RELEASE_LAG_CALENDAR_DAYS
    )
    assert by_obs[date(2026, 9, 14)].release_date == date(2026, 9, 14) + timedelta(
        days=DAILY_RELEASE_LAG_CALENDAR_DAYS
    )


def test_mmf_uses_frozen_month_end_lag_and_gzip(monkeypatch):
    client = OfrStfmClient(api_key="", allow_public_csv=False, include_keep_comparators=False)
    payload = [["2026-07-31", 8411936812496.55]]
    raw = gzip.compress(json.dumps(payload).encode("utf-8"))

    def fake_urlopen(request, timeout):
        assert MNEMONIC_MMF_TOTAL in str(request.full_url)
        return _FakeResponse(raw)

    monkeypatch.setattr(ofr_stfm_client, "urlopen", fake_urlopen)
    rows = client.fetch_mnemonic(MNEMONIC_MMF_TOTAL)
    assert len(rows) == 1
    assert rows[0].observation_date == date(2026, 7, 31)
    assert rows[0].release_date == date(2026, 7, 31) + timedelta(days=MMF_RELEASE_LAG_CALENDAR_DAYS)
    assert rows[0].release_date == date(2026, 8, 20)


def test_frozen_mnemonic_set_is_exactly_five_series():
    assert FROZEN_MNEMONICS == (
        "REPO-DVP_TV_TOT-P",
        "REPO-GCF_TV_TOT-P",
        "MMF-MMF_TOT-M",
        "FNYR-SOFR-A",
        "FNYR-EFFR-A",
    )


def test_fetch_bundle_uses_min_of_all_four_daily_series(monkeypatch):
    client = OfrStfmClient(api_key="", allow_public_csv=False, include_keep_comparators=False)
    payloads = {
        "REPO-DVP_TV_TOT-P": [["2026-01-02", 1.0], ["2026-01-05", 2.0], ["2026-01-06", 3.0]],
        "REPO-GCF_TV_TOT-P": [["2026-01-02", 1.0], ["2026-01-05", 2.0]],
        "MMF-MMF_TOT-M": [["2024-01-31", 8e12]] * 24,
        "FNYR-SOFR-A": [["2026-01-02", 3.5], ["2026-01-05", 3.5], ["2026-01-06", 3.5]],
        "FNYR-EFFR-A": [["2026-01-02", 3.5], ["2026-01-05", 3.5], ["2026-01-06", 3.5]],
    }

    def fake_urlopen(request, timeout):
        url = str(request.full_url)
        for mnemonic, payload in payloads.items():
            if mnemonic in url:
                return _FakeResponse(json.dumps(payload).encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr(ofr_stfm_client, "urlopen", fake_urlopen)
    bundle = client.fetch_bundle()
    assert bundle.history_plan["gcf_count"] == 2
    assert bundle.history_plan["dvp_count"] == 3
    assert bundle.history_plan["meets_stfm_hard_minimum"] is False
    assert bundle.status == "data_blocked"
