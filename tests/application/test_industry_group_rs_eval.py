from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from application.industry_group_rs_eval_service import (
    IndustryGroupRsEvalService,
    NestedModelObservation,
)
from application.scan_service import _rank_results
from config.industry_groups import IndustryGroupMembership


def _membership(ticker: str, group_id: str, name: str) -> IndustryGroupMembership:
    return IndustryGroupMembership(
        ticker=ticker,
        group_id=group_id,
        group_name=name,
        gics_code=group_id.replace("gics-", ""),
        gics_industry_group=name,
        sector="Information Technology",
    )


def _observation(
    day: date,
    ticker: str,
    *,
    raw_strength: float,
    group_avg: float,
    excess_20d: float,
    group_id: str,
) -> NestedModelObservation:
    return NestedModelObservation(
        as_of=day,
        ticker=ticker,
        raw_strength_pct=raw_strength,
        universe_percentile=50.0,
        sector_percentile=50.0,
        market_relative_pct=raw_strength,
        sector_relative_pct=raw_strength,
        group_id=group_id,
        group_avg_rs_pct=group_avg,
        group_rank=1.0 if group_avg > 0 else 2.0,
        group_rank_percentile=80.0 if group_avg > 0 else 20.0,
        rank_delta_1w=group_avg,
        rank_delta_1m=group_avg,
        rank_delta_3m=group_avg,
        rank_delta_6m=group_avg,
        rs_ratio=group_avg,
        rs_momentum=group_avg,
        excess_5d=excess_20d / 2,
        excess_20d=excess_20d,
        excess_60d=excess_20d * 1.5,
        singleton_group=False,
    )


def _panel(*, correlated_group: bool) -> list[NestedModelObservation]:
    tickers = [f"T{index:02d}" for index in range(12)]
    rows: list[NestedModelObservation] = []
    start = date(2024, 1, 5)
    for week in range(30):
        as_of = start + timedelta(days=week * 7)
        for index, ticker in enumerate(tickers):
            group_id = "gics-a" if index < 6 else "gics-b"
            noise = ((week + index) % 5 - 2) * 0.15
            if correlated_group:
                group_avg = 8.0 if index < 6 else -8.0
                raw_strength = noise
                excess = group_avg + noise
            else:
                group_avg = 0.0
                raw_strength = noise
                excess = ((week * 3 + index) % 7 - 3) * 0.4
            rows.append(
                _observation(
                    as_of,
                    ticker,
                    raw_strength=raw_strength,
                    group_avg=group_avg,
                    excess_20d=excess,
                    group_id=group_id,
                )
            )
    return rows


def _mapping_for_panel() -> dict[str, IndustryGroupMembership]:
    mapping: dict[str, IndustryGroupMembership] = {}
    for index in range(12):
        ticker = f"T{index:02d}"
        group_id = "gics-a" if index < 6 else "gics-b"
        mapping[ticker] = _membership(ticker, group_id, "Group A" if index < 6 else "Group B")
    return mapping


def test_nested_model_reports_success_when_group_rs_adds_20d_ic_lift():
    mapping = _mapping_for_panel()
    service = IndustryGroupRsEvalService(mapping=mapping)
    payload = service.evaluate_observations(
        _panel(correlated_group=True),
        universe=list(mapping),
        history_sessions_max=520,
    )

    assert payload["status"] == "research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["pre_registration"]["primary_horizon_days"] == 20
    assert payload["verdict"]["live_surface_changed"] is False
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["eligible_folds"] == 3
    assert "spearman_ic" in payload["verdict"]["winning_primary_metrics"]


def test_nested_model_fails_when_group_features_add_no_20d_lift():
    mapping = _mapping_for_panel()
    service = IndustryGroupRsEvalService(mapping=mapping)
    payload = service.evaluate_observations(
        _panel(correlated_group=False),
        universe=list(mapping),
        history_sessions_max=520,
    )

    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["winning_primary_metrics"] == []
    assert payload["deployment_guard"]["automatic_config_changes"] is False


def test_eval_aborts_when_group_map_coverage_is_below_80_percent():
    service = IndustryGroupRsEvalService(mapping={})
    payload = service.evaluate_observations(
        _panel(correlated_group=True)[:12],
        universe=["T00", "T01", "T02"],
        history_sessions_max=520,
    )

    assert payload["verdict"]["outcome"] == "aborted"
    assert payload["coverage"]["meets_minimum_coverage"] is False
    assert any("coverage" in reason.lower() for reason in payload["verdict"]["abort_reasons"])


def test_rank_results_still_sorts_by_live_scores_not_group_rs(monkeypatch):
    analyses = [
        SimpleNamespace(ticker="LOW_SCORE_HIGH_GROUP", long_score=20, short_score=18, long_label="Avoid", short_label="Avoid"),
        SimpleNamespace(ticker="HIGH_SCORE_LOW_GROUP", long_score=90, short_score=88, long_label="Strong Buy", short_label="Strong Setup"),
    ]
    monkeypatch.setattr("application.scan_service._passes_universe_filters", lambda analysis: True)
    monkeypatch.setattr(
        "application.scan_service._build_market_row",
        lambda analysis: {"ticker": analysis.ticker, "industry_group_rank": 1 if "LOW_SCORE" in analysis.ticker else 9},
    )
    monkeypatch.setattr(
        "application.scan_service._build_long_term_row",
        lambda analysis: {
            "ticker": analysis.ticker,
            "long_term_score": analysis.long_score,
            "recommendation_label": analysis.long_label,
            "industry_group_rank": 1 if "LOW_SCORE" in analysis.ticker else 9,
        },
    )
    monkeypatch.setattr(
        "application.scan_service._build_short_term_row",
        lambda analysis: {
            "ticker": analysis.ticker,
            "short_term_score": analysis.short_score,
            "recommendation_label": analysis.short_label,
            "ranking_bucket": "NO_SETUP",
            "industry_group_rank": 1 if "LOW_SCORE" in analysis.ticker else 9,
        },
    )

    _, long_rows, short_rows = _rank_results(analyses)

    assert [row["ticker"] for row in long_rows] == ["HIGH_SCORE_LOW_GROUP", "LOW_SCORE_HIGH_GROUP"]
    assert [row["ticker"] for row in short_rows] == ["HIGH_SCORE_LOW_GROUP", "LOW_SCORE_HIGH_GROUP"]
