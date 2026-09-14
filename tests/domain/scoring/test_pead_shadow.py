from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from domain.scoring.pead_shadow import (
    assign_event_date,
    horizon_return_pct,
    size_bucket_for_market_cap,
)


def test_horizon_return_matches_existing_three_session_definition():
    dates = pd.bdate_range("2026-04-27", "2026-05-08")
    close = pd.Series([100, 100, 100, 101, 102, 500, 600, 700, 800, 900], index=dates)
    close.index = pd.to_datetime(close.index).tz_localize(None)

    value, observed, complete = horizon_return_pct(
        close,
        date(2026, 4, 30),
        as_of=date(2026, 5, 1),
        sessions=3,
    )

    assert value == pytest.approx(2.0)
    assert observed == 2
    assert complete is False


def test_assign_event_date_does_not_reuse_filings():
    used: set[date] = set()
    first, first_source = assign_event_date(
        "2025-12-31",
        filing_dates=[date(2026, 1, 15), date(2026, 4, 16)],
        used_filings=used,
    )
    second, second_source = assign_event_date(
        "2026-03-31",
        filing_dates=[date(2026, 1, 15), date(2026, 4, 16)],
        used_filings=used,
    )
    stale, stale_source = assign_event_date(
        "2025-06-30",
        filing_dates=[date(2026, 1, 15), date(2026, 4, 16)],
        used_filings=used,
    )

    assert first == date(2026, 1, 15)
    assert first_source == "sec_filing"
    assert second == date(2026, 4, 16)
    assert second_source == "sec_filing"
    assert stale == date(2025, 6, 30)
    assert stale_source == "fiscal_period"


def test_size_buckets_are_pre_registered():
    assert size_bucket_for_market_cap(None) == "unknown"
    assert size_bucket_for_market_cap(1_000_000_000) == "small"
    assert size_bucket_for_market_cap(5_000_000_000) == "mid"
    assert size_bucket_for_market_cap(50_000_000_000) == "large"
    assert size_bucket_for_market_cap(250_000_000_000) == "mega"
