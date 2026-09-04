from __future__ import annotations

from types import SimpleNamespace

from dataclasses import replace

from application.scan_service import (
    _assign_relative_strength_percentiles,
    _earnings_intelligence_fields,
    _passes_universe_filters,
    _rank_results,
)
from domain.scoring.earnings_intelligence import (
    build_unavailable_earnings_intelligence_view,
)
from domain.scoring.relative_strength import build_unavailable_relative_strength_view


def _analysis(ticker: str, history_points: int, market_cap: float, volume: float = 0.0):
    return SimpleNamespace(
        ticker=ticker,
        data_source="cached_real",
        snapshot={
            "current_price": 22.3,
            "avg_volume_20": volume,
        },
        fundamentals={
            "marketCap": market_cap,
        },
        enriched_history=[object()] * history_points,
    )


def test_emerging_spcx_can_pass_with_short_history_and_missing_market_cap():
    assert _passes_universe_filters(_analysis("SPCX", history_points=1, market_cap=0.0))


def test_regular_universe_still_requires_standard_history_and_market_cap():
    assert not _passes_universe_filters(_analysis("AAPL", history_points=1, market_cap=0.0, volume=0.0))


def test_relative_strength_percentiles_rank_universe_and_sector_peers():
    results = []
    for index, raw_strength in enumerate((-8.0, -2.0, 1.0, 5.0, 12.0)):
        base = build_unavailable_relative_strength_view(
            sector="Technology",
            sector_symbol="XLK",
            message="fixture",
        )
        results.append(
            SimpleNamespace(
                sector="Technology",
                relative_strength_view=replace(
                    base,
                    status="outperforming",
                    score=50 + index * 5,
                    coverage_score=100,
                    raw_strength_pct=raw_strength,
                ),
            )
        )

    _assign_relative_strength_percentiles(results)

    assert results[0].relative_strength_view.universe_percentile == 0
    assert results[2].relative_strength_view.universe_percentile == 50
    assert results[-1].relative_strength_view.universe_percentile == 100
    assert results[-1].relative_strength_view.sector_percentile == 100


def test_scan_exposes_earnings_event_risk_without_applied_impact():
    base = build_unavailable_earnings_intelligence_view("fixture")
    analysis = SimpleNamespace(
        earnings_intelligence_view=replace(
            base,
            status="strong",
            score=78,
            coverage_score=90,
            next_earnings_date="2026-07-30",
            days_to_earnings=2,
            event_risk="high",
            latest_surprise_pct=4.2,
            applied_impact=0,
        )
    )

    fields = _earnings_intelligence_fields(analysis)

    assert fields["earnings_intelligence_score"] == 78
    assert fields["earnings_event_risk"] == "high"
    assert fields["days_to_earnings"] == 2
    assert fields["earnings_intelligence_applied_impact"] == 0


def test_rank_results_keeps_every_recommendation_tier(monkeypatch):
    analyses = [
        SimpleNamespace(ticker="BUY", long_score=82, short_score=77, long_label="Strong Buy", short_label="Strong Setup"),
        SimpleNamespace(ticker="HOLD", long_score=52, short_score=46, long_label="Hold", short_label="Neutral"),
        SimpleNamespace(ticker="AVOID", long_score=20, short_score=18, long_label="Avoid", short_label="Avoid"),
    ]

    monkeypatch.setattr("application.scan_service._passes_universe_filters", lambda analysis: True)
    monkeypatch.setattr(
        "application.scan_service._build_market_row",
        lambda analysis: {"ticker": analysis.ticker},
    )
    monkeypatch.setattr(
        "application.scan_service._build_long_term_row",
        lambda analysis: {
            "ticker": analysis.ticker,
            "long_term_score": analysis.long_score,
            "recommendation_label": analysis.long_label,
        },
    )
    monkeypatch.setattr(
        "application.scan_service._build_short_term_row",
        lambda analysis: {
            "ticker": analysis.ticker,
            "short_term_score": analysis.short_score,
            "recommendation_label": analysis.short_label,
            "ranking_bucket": "NO_SETUP",
        },
    )

    _, long_rows, short_rows = _rank_results(analyses)

    assert [row["recommendation_label"] for row in long_rows] == ["Strong Buy", "Hold", "Avoid"]
    assert [row["recommendation_label"] for row in short_rows] == ["Strong Setup", "Neutral", "Avoid"]
