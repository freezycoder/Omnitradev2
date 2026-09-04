from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from application import ticker_service
from domain.scoring.relative_strength import build_unavailable_relative_strength_view


def _analysis(raw_strength: float):
    base = build_unavailable_relative_strength_view(
        sector="Technology",
        sector_symbol="XLK",
        message="fixture",
    )
    return SimpleNamespace(
        ticker="AAPL",
        relative_strength_view=replace(
            base,
            status="outperforming",
            score=65,
            coverage_score=100,
            raw_strength_pct=raw_strength,
        ),
    )


def test_latest_scan_percentiles_enrich_matching_ticker_snapshot(monkeypatch):
    analysis = _analysis(8.25)
    monkeypatch.setattr(
        ticker_service,
        "load_latest_view_scan",
        lambda: {
            "market_rows": [
                {
                    "ticker": "AAPL",
                    "relative_strength_raw_pct": 8.25,
                    "relative_strength_universe_percentile": 84,
                    "relative_strength_sector_percentile": 72,
                }
            ]
        },
    )

    result = ticker_service.enrich_relative_strength_with_latest_scan(analysis)

    assert result.relative_strength_view.universe_percentile == 84
    assert result.relative_strength_view.sector_percentile == 72


def test_latest_scan_percentiles_do_not_cross_different_strength_snapshot(monkeypatch):
    analysis = _analysis(8.25)
    monkeypatch.setattr(
        ticker_service,
        "load_latest_view_scan",
        lambda: {
            "market_rows": [
                {
                    "ticker": "AAPL",
                    "relative_strength_raw_pct": 9.0,
                    "relative_strength_universe_percentile": 84,
                }
            ]
        },
    )

    result = ticker_service.enrich_relative_strength_with_latest_scan(analysis)

    assert result.relative_strength_view.universe_percentile is None
