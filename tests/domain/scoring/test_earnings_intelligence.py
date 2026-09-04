from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from domain.scoring.earnings_intelligence import (
    build_earnings_intelligence_view,
    build_unavailable_earnings_intelligence_view,
    earnings_intelligence_view_from_dict,
)
from providers.events.sec_edgar_client import SecEventBundle, SecFilingEvent


def _history(*, rising: bool = True) -> pd.DataFrame:
    dates = pd.bdate_range("2026-04-01", "2026-07-28")
    start = 100.0
    step = 0.35 if rising else -0.25
    closes = [start + index * step for index in range(len(dates))]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": [1_000_000] * len(dates),
        },
        index=dates,
    )


def _earnings_filing(filed_at: str = "2026-05-01") -> SecEventBundle:
    return SecEventBundle(
        ticker="AAPL",
        cik="320193",
        status="available",
        retrieved_at=datetime.now(UTC).isoformat(),
        events=[
            SecFilingEvent(
                form="8-K",
                filed_at=filed_at,
                category="earnings_update",
                direction=0,
                importance=2,
                summary="Results were reported.",
                url="https://example.com/filing",
                accession_number="fixture",
                items=["2.02"],
            )
        ],
    )


def _history_rows(surprises: list[float]) -> list[dict[str, object]]:
    periods = ["2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    return [
        {
            "period": period,
            "year": 2026 if index < 2 else 2025,
            "quarter": index + 1,
            "actual": 2.0 + surprise / 100,
            "estimate": 2.0,
            "surprise": surprise / 100,
            "surprisePercent": surprise,
        }
        for index, (period, surprise) in enumerate(zip(periods, surprises))
    ]


def test_strong_earnings_remains_shadow_only_and_flags_imminent_event():
    view = build_earnings_intelligence_view(
        stock_history=_history(),
        earnings_history=_history_rows([8.0, 6.0, 4.0, 3.0]),
        estimate_context={
            "next_earnings_date": "2026-07-30",
            "current_quarter": {
                "average": 1.90,
                "low": 1.82,
                "high": 1.99,
                "year_ago_eps": 1.57,
                "analyst_count": 31,
                "growth_pct": 20.4,
            },
            "revisions": {"up_30d": 24, "down_30d": 0},
        },
        sec_bundle=_earnings_filing(),
        as_of_date=date(2026, 7, 28),
    )

    assert view.score is not None and view.score >= 70
    assert view.status == "strong"
    assert view.applied_impact == 0
    assert view.coverage_score == 100
    assert view.event_risk == "high"
    assert view.days_to_earnings == 2
    assert view.beat_rate_pct == 100
    assert view.net_revisions_30d == 24
    assert view.post_filing_3d_return_pct is not None


def test_negative_surprises_revisions_and_growth_produce_caution():
    view = build_earnings_intelligence_view(
        stock_history=_history(rising=False),
        earnings_history=_history_rows([-9.0, -6.0, -4.0, -2.0]),
        estimate_context={
            "next_earnings_date": "2026-09-15",
            "current_quarter": {
                "average": 1.20,
                "year_ago_eps": 1.80,
                "analyst_count": 15,
                "growth_pct": -25.0,
            },
            "revisions": {"up_30d": 1, "down_30d": 12},
        },
        sec_bundle=_earnings_filing(),
        as_of_date=date(2026, 7, 28),
    )

    assert view.score is not None and view.score <= 30
    assert view.status == "deteriorating"
    assert view.latest_surprise_pct == -9.0
    assert view.net_revisions_30d == -11
    assert view.event_risk == "normal"


def test_post_filing_reaction_does_not_use_prices_after_as_of_date():
    dates = pd.bdate_range("2026-04-27", "2026-05-08")
    history = pd.DataFrame(
        {
            "Close": [100, 100, 100, 101, 102, 500, 600, 700, 800, 900],
        },
        index=dates,
    )

    view = build_earnings_intelligence_view(
        stock_history=history,
        earnings_history=_history_rows([2.0, 1.0, 0.5, 0.2]),
        estimate_context={},
        sec_bundle=_earnings_filing("2026-04-30"),
        as_of_date=date(2026, 5, 1),
    )

    assert view.post_filing_3d_return_pct == 2.0


def test_old_cache_falls_back_to_unavailable_view():
    view = earnings_intelligence_view_from_dict(None)

    assert view.status == "unavailable"
    assert view.score is None
    assert view.applied_impact == 0


def test_earnings_view_round_trips_through_cache_dict():
    original = build_unavailable_earnings_intelligence_view("fixture")

    restored = earnings_intelligence_view_from_dict(original.to_dict())

    assert restored == original
