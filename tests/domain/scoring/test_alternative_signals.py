from __future__ import annotations

from datetime import UTC, datetime

from domain.scoring.alternative_signals import build_alternative_signal_view
from providers.events.sec_edgar_client import SecEventBundle, SecFilingEvent
from providers.macro.fred_client import FredMacroBundle, FredSeriesSnapshot
from providers.news.news_provider import NewsItem


def _macro_series(key: str, value: float, change: float | None = None) -> FredSeriesSnapshot:
    return FredSeriesSnapshot(
        key=key,
        series_id=key,
        label=key,
        unit="index",
        latest_value=value,
        latest_date="2026-07-27",
        prior_value=value - change if change is not None else None,
        prior_date="2026-04-27" if change is not None else None,
        change=change,
    )


def test_alternative_signal_is_capped_and_never_applied_live():
    now = datetime.now(UTC).isoformat()
    sec = SecEventBundle(
        ticker="AAPL",
        cik="0000320193",
        status="available",
        retrieved_at=now,
        events=[
            SecFilingEvent("4", "2026-07-25", "insider_purchase", 1, 3, "Insider purchase.", "https://sec", "1"),
            SecFilingEvent("8-K", "2026-07-24", "material_agreement", 1, 3, "Material agreement.", "https://sec", "2"),
        ],
    )
    news = [
        NewsItem(
            "Company raises guidance",
            "",
            "Reuters",
            "https://news",
            now,
            event_type="guidance",
            source_quality="established_reporting",
            relevance_score=100,
            direction=1,
            importance=4,
        )
    ]
    macro = FredMacroBundle(
        status="available",
        retrieved_at=now,
        series={
            "yield_curve_10y_2y": _macro_series("yield_curve_10y_2y", 0.8),
            "high_yield_spread": _macro_series("high_yield_spread", 2.8, -1.2),
            "financial_conditions": _macro_series("financial_conditions", -0.2, -0.1),
            "fed_funds": _macro_series("fed_funds", 3.5),
        },
    )

    view = build_alternative_signal_view(
        sec_bundle=sec,
        news_items=news,
        news_status_message=None,
        macro_bundle=macro,
    )

    assert view.mode == "shadow"
    assert view.modeled_impact == 10
    assert view.applied_impact == 0
    assert view.score == 100
    assert view.coverage_score == 100


def test_missing_sources_are_limited_not_neutral_evidence():
    view = build_alternative_signal_view(
        sec_bundle=None,
        news_items=[],
        news_status_message="Finnhub API key is not configured.",
        macro_bundle=None,
    )

    assert view.status == "limited"
    assert view.coverage_score == 0
    assert view.modeled_impact == 0
    assert view.applied_impact == 0
    assert len(view.warnings) == 3
