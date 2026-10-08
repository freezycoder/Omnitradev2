from __future__ import annotations

import json
from datetime import date, timedelta

from application.market_breadth_eval_service import (
    MarketBreadthEvalService,
    ShadowHitObservation,
    shadow_hit_from_row,
    signed_shadow_score,
)
from config.market_breadth import EQUAL_WEIGHT_PROXY_LABEL
from domain.scoring.market_breadth import BreadthDailySnapshot, BreadthGateDecision, BreadthPanel
from config.market_breadth import breadth_recipe_manifest


START = date(2024, 1, 5)


def _gate(status: str, pct_above: float) -> BreadthGateDecision:
    return BreadthGateDecision(
        status=status,  # type: ignore[arg-type]
        pct_above_50dma=pct_above,
        spy_return_nd=1.0 if status != "closed" else 1.0,
        ad_line_change_nd=5.0 if status == "open" else -4.0,
        coverage_50dma=0.95,
        reasons=("fixture",),
    )


def _snapshot(as_of: date, status: str, pct_above: float) -> BreadthDailySnapshot:
    return BreadthDailySnapshot(
        as_of=as_of,
        universe_size=12,
        names_quoted=12,
        advances=8 if status == "open" else 3,
        declines=4 if status == "open" else 9,
        unchanged=0,
        advance_decline_line=20.0,
        ad_line_change_nd=5.0 if status == "open" else -4.0,
        up_volume=8_000_000,
        down_volume=2_000_000,
        up_down_volume_ratio=4.0 if status == "open" else 0.4,
        pct_above_20dma=pct_above + 5,
        pct_above_50dma=pct_above,
        pct_above_200dma=pct_above - 5,
        coverage_20dma=0.95,
        coverage_50dma=0.95,
        coverage_200dma=0.90,
        spy_return_pct=0.4,
        equal_weight_return_pct=0.2 if status == "open" else -0.3,
        spy_minus_equal_weight_pct=0.2 if status == "open" else 0.7,
        rsp_return_pct=None,
        spy_minus_rsp_pct=None,
        cap_vs_equal_weight_proxy=EQUAL_WEIGHT_PROXY_LABEL,
        spy_return_nd=1.0,
        new_highs_252=4,
        new_lows_252=1,
        gate=_gate(status, pct_above),
    )


def _panel(dates: list[date], status_for_date) -> BreadthPanel:
    rows = tuple(
        _snapshot(as_of, status_for_date(as_of), 70.0 if status_for_date(as_of) == "open" else 40.0)
        for as_of in dates
    )
    return BreadthPanel(
        recipe=breadth_recipe_manifest(),
        universe=tuple(f"T{index:02d}" for index in range(12)),
        universe_size=12,
        rows=rows,
        rsp_available=False,
        cap_vs_equal_weight_proxy=EQUAL_WEIGHT_PROXY_LABEL,
        history_sessions_max=520,
        coverage={
            "universe_size": 12,
            "session_count": len(rows),
            "mean_quoted_share": 1.0,
            "mean_coverage_20dma": 0.95,
            "mean_coverage_50dma": 0.95,
            "mean_coverage_200dma": 0.90,
            "meets_minimum_coverage": True,
            "gate_open_days": sum(row.gate.status == "open" for row in rows),
            "gate_closed_days": sum(row.gate.status == "closed" for row in rows),
            "gate_unknown_days": 0,
            "rsp_available": False,
            "cap_vs_equal_weight_proxy": EQUAL_WEIGHT_PROXY_LABEL,
        },
        abort_reasons=(),
    )


def _hit(
    day: date,
    ticker: str,
    *,
    signed: float,
    realized: float,
    universe_percentile: float,
    pct_above: float,
) -> ShadowHitObservation:
    return ShadowHitObservation(
        signal_id=f"{ticker}-{day.isoformat()}",
        ticker=ticker,
        signal_date=day,
        realized_return_pct=realized,
        rs_score=universe_percentile,
        rs_universe_percentile=universe_percentile,
        rs_sector_percentile=universe_percentile,
        earnings_score=50.0 + signed,
        form4_impact=1.0 if signed > 0 else -1.0,
        signed_shadow_score=signed,
        daily_mean_universe_percentile=50.0,
        daily_median_universe_percentile=50.0,
        pct_above_20dma=pct_above + 5,
        pct_above_50dma=pct_above,
        pct_above_200dma=pct_above - 5,
        ad_line_change_nd=5.0 if pct_above >= 55 else -4.0,
        up_down_volume_ratio=3.0 if pct_above >= 55 else 0.5,
        spy_minus_equal_weight_pct=0.1 if pct_above >= 55 else 0.8,
        gate_status="open" if pct_above >= 55 else "closed",
    )


def _dates(weeks: int = 30) -> list[date]:
    return [START + timedelta(days=week * 7) for week in range(weeks)]


def _gate_lift_hits(*, invert_closed: bool, regime_premium: float = 0.0) -> list[ShadowHitObservation]:
    tickers = [f"T{index:02d}" for index in range(12)]
    rows: list[ShadowHitObservation] = []
    for week, as_of in enumerate(_dates()):
        open_week = week % 2 == 0
        pct_above = 70.0 if open_week else 40.0
        for index, ticker in enumerate(tickers):
            signed = (index - 5.5) * 4
            realized = signed / 8
            if open_week:
                realized += regime_premium
            if invert_closed and not open_week:
                realized = -signed / 8
            rows.append(
                _hit(
                    as_of,
                    ticker,
                    signed=signed,
                    realized=realized,
                    universe_percentile=50 + signed,
                    pct_above=pct_above,
                )
            )
    return rows


def test_shadow_hit_parser_uses_sec_events_not_blended_alt_overlay():
    row = {
        "signal_id": "s1",
        "ticker": "aapl",
        "created_at": "2026-03-01T12:00:00+00:00",
        "realized_return_pct": 1.5,
        "feature_snapshot_json": json.dumps(
            {
                "relative_strength": {"score": 72, "universe_percentile": 81, "sector_percentile": 70},
                "earnings_intelligence": {"score": 64},
                "alternative_signal": {
                    "modeled_impact": 9,
                    "components": [
                        {"key": "sec_events", "modeled_impact": 3},
                        {"key": "verified_news", "modeled_impact": 4},
                    ],
                },
            }
        ),
    }

    hit = shadow_hit_from_row(row)

    assert hit is not None
    assert hit.ticker == "AAPL"
    assert hit.form4_impact == 3
    assert hit.rs_universe_percentile == 81
    assert signed_shadow_score(
        rs_score=72,
        rs_universe_percentile=81,
        earnings_score=64,
        form4_impact=3,
    ) == hit.signed_shadow_score


def test_gate_reports_success_when_open_days_have_ic_lift():
    dates = _dates()
    panel = _panel(dates, lambda as_of: "open" if ((as_of - START).days // 7) % 2 == 0 else "closed")
    payload = MarketBreadthEvalService(hits=_gate_lift_hits(invert_closed=True, regime_premium=1.5)).evaluate_panel(panel)

    assert payload["status"] == "research_only"
    assert payload["deployment_guard"]["live_recommendation_changes"] is False
    assert payload["pre_registration"]["gate_is_fitted"] is False
    assert payload["latest_view"]["applied_impact"] == 0
    assert payload["verdict"]["live_surface_changed"] is False
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["eligible_gate_folds"] == 3
    assert payload["verdict"]["winning_primary_metrics"]


def test_gate_fails_when_closed_days_are_not_worse():
    dates = _dates()
    panel = _panel(dates, lambda as_of: "open" if ((as_of - START).days // 7) % 2 == 0 else "closed")
    payload = MarketBreadthEvalService(hits=_gate_lift_hits(invert_closed=False)).evaluate_panel(panel)

    assert payload["deployment_guard"]["automatic_config_changes"] is False
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["winning_primary_metrics"] == []


def test_eval_aborts_when_panel_coverage_fails():
    dates = _dates(8)
    panel = _panel(dates, lambda _as_of: "open")
    panel = BreadthPanel(
        recipe=panel.recipe,
        universe=panel.universe,
        universe_size=panel.universe_size,
        rows=panel.rows,
        rsp_available=False,
        cap_vs_equal_weight_proxy=EQUAL_WEIGHT_PROXY_LABEL,
        history_sessions_max=120,
        coverage={**panel.coverage, "meets_minimum_coverage": False, "mean_coverage_200dma": 0.0},
        abort_reasons=("Longest overlapping history is 120 sessions; 200 are required for a 200 DMA.",),
    )
    payload = MarketBreadthEvalService(hits=_gate_lift_hits(invert_closed=True)[:40]).evaluate_panel(panel)

    assert payload["verdict"]["outcome"] == "aborted"
    assert any("200" in reason for reason in payload["verdict"]["abort_reasons"])


def test_nested_model_flags_redundancy_with_rs_percentile_aggregates():
    dates = _dates()
    hits: list[ShadowHitObservation] = []
    for as_of in dates:
        for index in range(12):
            percentile = 20 + index * 5
            hits.append(
                _hit(
                    as_of,
                    f"T{index:02d}",
                    signed=percentile - 50,
                    realized=(percentile - 50) / 10,
                    universe_percentile=percentile,
                    pct_above=percentile,
                )
            )
    panel = _panel(dates, lambda _as_of: "open")
    payload = MarketBreadthEvalService(hits=hits).evaluate_panel(panel)

    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["breadth_redundant_with_rs_percentiles"] is True
