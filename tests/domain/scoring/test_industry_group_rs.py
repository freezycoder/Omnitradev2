from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd

from domain.scoring.industry_group_rs import (
    assign_industry_group_relative_strength,
    compute_rrg_frame,
    rrg_quadrant,
    rrg_recipe_manifest,
)
from domain.scoring.relative_strength import (
    build_relative_strength_view,
    build_unavailable_relative_strength_view,
    compute_raw_strength_frame,
)


def _history(start: float, end: float, periods: int = 300, origin: str = "2023-01-02") -> pd.DataFrame:
    values = [start + (end - start) * index / (periods - 1) for index in range(periods)]
    return pd.DataFrame(
        {
            "Open": values,
            "High": values,
            "Low": values,
            "Close": values,
            "Volume": [1_000_000] * periods,
        },
        index=pd.bdate_range(origin, periods=periods),
    )


def _result(
    ticker: str,
    raw_strength: float,
    *,
    history: pd.DataFrame | None = None,
    sector: str = "Technology",
):
    base = build_unavailable_relative_strength_view(
        sector=sector,
        sector_symbol="XLK",
        message="fixture",
    )
    return SimpleNamespace(
        ticker=ticker,
        sector=sector,
        history=history if history is not None else pd.DataFrame(),
        relative_strength_view=replace(
            base,
            status="outperforming",
            score=60,
            coverage_score=100,
            raw_strength_pct=raw_strength,
        ),
    )


def test_rolling_raw_strength_matches_point_in_time_view():
    stock = _history(100, 160, periods=280)
    market = _history(100, 120, periods=280)
    sector = _history(100, 130, periods=280)

    view = build_relative_strength_view(
        stock_history=stock,
        market_history=market,
        sector_history=sector,
        sector="Technology",
        sector_symbol="XLK",
    )
    frame = compute_raw_strength_frame(stock, market, sector)

    assert view.raw_strength_pct is not None
    assert abs(float(frame["raw_strength_pct"].iloc[-1]) - float(view.raw_strength_pct)) < 0.05


def test_rrg_quadrants_are_exhaustive_sign_pairs():
    assert rrg_quadrant(0.4, 0.2) == "Leading"
    assert rrg_quadrant(0.4, -0.2) == "Weakening"
    assert rrg_quadrant(-0.4, -0.2) == "Lagging"
    assert rrg_quadrant(-0.4, 0.2) == "Improving"
    assert rrg_quadrant(0.0, 0.0) == "Leading"


def test_rrg_recipe_is_frozen_before_eval():
    recipe = rrg_recipe_manifest()

    assert recipe["frozen"] is True
    assert recipe["weekly_anchor"] == "W-FRI"
    assert recipe["zscore_weeks"] == 52
    assert recipe["min_weeks"] == 26


def test_group_assignment_is_shadow_only_and_ranks_stronger_groups_first():
    nvda = _result("NVDA", 12.0, history=_history(100, 180, periods=280))
    amd = _result("AMD", 10.0, history=_history(100, 170, periods=280))
    msft = _result("MSFT", -4.0, history=_history(100, 110, periods=280))
    orcl = _result("ORCL", -6.0, history=_history(100, 105, periods=280))
    market = _history(100, 120, periods=280)

    summary = assign_industry_group_relative_strength(
        [nvda, amd, msft, orcl],
        market_history=market,
        sector_histories={"Technology": market},
    )

    assert nvda.industry_group_rs_view.mode == "shadow"
    assert nvda.industry_group_rs_view.applied_impact == 0
    assert msft.industry_group_rs_view.applied_impact == 0
    assert nvda.industry_group_rs_view.group_id == amd.industry_group_rs_view.group_id
    assert nvda.industry_group_rs_view.group_rank == 1
    assert msft.industry_group_rs_view.group_rank == 2
    assert nvda.industry_group_rs_view.taxonomy == "gics_subindustry_proxy"
    assert summary["coverage"]["meets_minimum_coverage"] is True


def test_weekly_rrg_zscores_use_own_trailing_history():
    weekly = pd.date_range("2023-01-06", periods=80, freq="W-FRI")
    leading_weekly = np.concatenate([np.zeros(50), np.linspace(1, 40, 30) ** 2])
    lagging_weekly = -leading_weekly
    daily_index = pd.bdate_range(weekly[0], weekly[-1])
    frame = pd.DataFrame(
        {
            "leading": pd.Series(leading_weekly, index=weekly).reindex(daily_index).ffill(),
            "lagging": pd.Series(lagging_weekly, index=weekly).reindex(daily_index).ffill(),
        }
    )

    rrg = compute_rrg_frame(frame)
    leading_ratio = rrg["rs_ratio"]["leading"].dropna().iloc[-1]
    leading_momentum = rrg["rs_momentum"]["leading"].dropna().iloc[-1]
    lagging_ratio = rrg["rs_ratio"]["lagging"].dropna().iloc[-1]
    lagging_momentum = rrg["rs_momentum"]["lagging"].dropna().iloc[-1]

    assert leading_ratio > 0
    assert leading_momentum > 0
    assert lagging_ratio < 0
    assert lagging_momentum < 0
    assert rrg_quadrant(float(leading_ratio), float(leading_momentum)) == "Leading"
    assert rrg_quadrant(float(lagging_ratio), float(lagging_momentum)) == "Lagging"
