from __future__ import annotations

import pandas as pd

from domain.scoring.relative_strength import (
    build_relative_strength_view,
    relative_strength_view_from_dict,
)


def _history(start: float, end: float, periods: int = 300) -> pd.DataFrame:
    values = [start + (end - start) * index / (periods - 1) for index in range(periods)]
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Volume": [1_000_000] * periods,
        },
        index=pd.bdate_range("2025-01-01", periods=periods),
    )


def test_relative_strength_leader_never_changes_live_score():
    view = build_relative_strength_view(
        stock_history=_history(100, 180),
        market_history=_history(100, 120),
        sector_history=_history(100, 130),
        sector="Technology",
        sector_symbol="XLK",
    )

    assert view.mode == "shadow"
    assert view.status == "leader"
    assert view.score is not None and view.score >= 70
    assert view.applied_impact == 0
    assert view.coverage_score == 100
    assert view.market_relative_pct is not None and view.market_relative_pct > 0
    assert view.sector_relative_pct is not None and view.sector_relative_pct > 0


def test_missing_sector_benchmark_reduces_coverage_without_becoming_neutral():
    view = build_relative_strength_view(
        stock_history=_history(100, 140),
        market_history=_history(100, 120),
        sector_history=pd.DataFrame(),
        sector="Unknown",
        sector_symbol=None,
    )

    assert view.score is not None
    assert view.coverage_score == 60
    assert view.sector_relative_pct is None
    assert view.warnings


def test_benchmarks_are_clipped_to_stock_as_of_date():
    stock = _history(100, 150, periods=280)
    extended_market = _history(100, 500, periods=320)
    aligned_market = extended_market.loc[extended_market.index <= stock.index[-1]]

    clipped = build_relative_strength_view(
        stock_history=stock,
        market_history=extended_market,
        sector_history=aligned_market,
        sector="Technology",
        sector_symbol="XLK",
    )
    aligned = build_relative_strength_view(
        stock_history=stock,
        market_history=aligned_market,
        sector_history=aligned_market,
        sector="Technology",
        sector_symbol="XLK",
    )

    assert clipped.market_relative_pct == aligned.market_relative_pct


def test_cached_relative_strength_round_trip():
    view = build_relative_strength_view(
        stock_history=_history(100, 160),
        market_history=_history(100, 120),
        sector_history=_history(100, 130),
        sector="Technology",
        sector_symbol="XLK",
    )

    restored = relative_strength_view_from_dict(view.to_dict())

    assert restored == view
