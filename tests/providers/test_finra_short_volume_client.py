from __future__ import annotations

from datetime import date
from urllib.error import HTTPError

from providers.market.finra_short_volume_client import (
    FinraShortVolumeClient,
    daily_file_url,
    parse_regsho_text,
    reset_finra_short_volume_caches,
)


SAMPLE = """Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
20260911|AAPL|1000|10|5000|B,Q,N
20260911|AAPL|500|5|1000|Q
20260911|MSFT|2000|0|4000|Q
20260911|BAD||0|0|Q
"""


def test_parse_regsho_text_computes_ratio_and_consolidates_facility_rows():
    rows = {row.symbol: row for row in parse_regsho_text(SAMPLE, source_url="fixture")}

    assert rows["AAPL"].short_volume == 1500
    assert rows["AAPL"].total_volume == 6000
    assert rows["AAPL"].short_ratio == 0.25
    assert rows["AAPL"].exempt_share == 0.0025
    assert rows["AAPL"].provenance == "FINRA_OFF_EXCHANGE"
    assert rows["MSFT"].short_ratio == 0.5
    assert "BAD" not in rows


def test_parse_accepts_header_with_trailing_whitespace():
    payload = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market \n20260911|X|1|0|2|Q\n"
    rows = parse_regsho_text(payload)

    assert len(rows) == 1
    assert rows[0].symbol == "X"
    assert rows[0].short_ratio == 0.5


def test_client_uses_cached_file_and_skips_missing_days(tmp_path, monkeypatch):
    reset_finra_short_volume_caches()
    as_of = date(2026, 9, 11)
    fetched: list[str] = []

    def fake_fetch(url: str) -> bytes:
        fetched.append(url)
        if url.endswith("CNMSshvol20260911.txt"):
            return SAMPLE.encode("utf-8")
        raise HTTPError(url, 404, "missing", hdrs=None, fp=None)

    client = FinraShortVolumeClient(cache_dir=tmp_path, fetch_bytes=fake_fetch)
    first = client.fetch_daily_file(as_of)
    second = client.fetch_daily_file(as_of)
    latest = client.get_latest_file(as_of=date(2026, 9, 13), lookback_calendar_days=5)
    missing = client.fetch_daily_file(date(2026, 9, 12))

    assert first.status == "available"
    assert first.row_for_symbol("AAPL") is not None
    assert second.row_for_symbol("MSFT").short_ratio == 0.5
    assert latest.as_of_date == as_of
    assert missing.status == "unavailable"
    assert fetched.count(daily_file_url(as_of)) == 1
    assert (tmp_path / "CNMSshvol20260911.txt").exists()
