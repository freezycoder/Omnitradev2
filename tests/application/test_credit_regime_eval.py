from __future__ import annotations

from datetime import date, timedelta

from application.credit_regime_eval_service import (
    CreditRegimeEvalService,
    LongScreenObservation,
    long_screen_from_row,
)
from config.credit_regime import ICE_REDISTRIBUTION_NOTICE, THROTTLE_WEIGHT, credit_recipe_manifest
from domain.scoring.credit_regime import CreditDailySnapshot, CreditPanel, evaluate_gate


START = date(2024, 1, 5)


def _decision(status: str) -> CreditGateDecision:
    if status == "throttle":
        return evaluate_gate(
            hy_oas=3.4,
            hy_oas_d20_bp=45.0,
            hy_oas_percentile_252=40.0,
            percentile_observations=200,
        )
    if status == "unknown":
        return evaluate_gate(
            hy_oas=None,
            hy_oas_d20_bp=None,
            hy_oas_percentile_252=None,
            percentile_observations=0,
        )
    return evaluate_gate(
        hy_oas=2.7,
        hy_oas_d20_bp=8.0,
        hy_oas_percentile_252=40.0,
        percentile_observations=200,
    )


def _snapshot(
    as_of: date,
    status: str,
    vol: float,
    *,
    credit_features: dict[str, float] | None = None,
) -> CreditDailySnapshot:
    gate = _decision(status)
    features = credit_features or {}
    hy_oas = features.get("hy_oas", gate.hy_oas)
    d20 = features.get("hy_oas_d20_bp", gate.hy_oas_d20_bp)
    d5 = features.get("hy_oas_d5_bp", 5.0 if status != "unknown" else None)
    gap = features.get("hy_ig_gap", None if hy_oas is None else hy_oas - 1.0)
    return CreditDailySnapshot(
        as_of=as_of,
        hy_oas=hy_oas,
        ig_oas=1.0,
        hy_ig_gap=gap,
        hy_oas_d20_bp=d20,
        hy_oas_d5_bp=d5,
        hy_oas_percentile_252=gate.hy_oas_percentile_252,
        percentile_observations=gate.percentile_observations,
        spy_return_pct=-0.8 if status == "throttle" else 0.4,
        spy_realized_vol_20d=vol,
        gate=gate,
    )


def _panel(dates: list[date], status_for_date, vol_for_date=None, credit_from_vol: bool = False) -> CreditPanel:
    if vol_for_date is None:
        vol_for_date = lambda as_of: 0.12 + (((as_of - START).days // 7) % 5) * 0.004
    rows = []
    for as_of in dates:
        vol = vol_for_date(as_of)
        credit_features = None
        if credit_from_vol:
            credit_features = {
                "hy_oas": vol,
                "hy_oas_d20_bp": vol,
                "hy_oas_d5_bp": vol,
                "hy_ig_gap": vol,
            }
        rows.append(_snapshot(as_of, status_for_date(as_of), vol, credit_features=credit_features))
    rows = tuple(rows)
    return CreditPanel(
        recipe=credit_recipe_manifest(),
        rows=rows,
        source="fixture",
        hy_count=520,
        ig_count=520,
        history_sessions=520,
        coverage={
            "hy_count": 520,
            "ig_count": 520,
            "session_count": len(rows),
            "data_blocked": False,
            "meets_hard_minimum": True,
            "meets_recommended_minimum": True,
            "velocity_ready_days": len(rows),
            "gate_full_days": sum(row.gate.status == "full" for row in rows),
            "gate_throttle_days": sum(row.gate.status == "throttle" for row in rows),
            "gate_unknown_days": 0,
        },
        abort_reasons=(),
    )


def _hit(
    day: date,
    ticker: str,
    *,
    realized: float,
    score: float,
    vol: float,
) -> LongScreenObservation:
    return LongScreenObservation(
        signal_id=f"{ticker}-{day.isoformat()}",
        ticker=ticker,
        signal_date=day,
        realized_return_pct=realized,
        long_term_score=score,
        recommendation_label="Buy",
        strategy_family="long_term_6m",
        spy_realized_vol_20d=vol,
        hy_oas=3.0,
        hy_oas_d20_bp=10.0,
        hy_oas_d5_bp=4.0,
        hy_ig_gap=1.8,
        pct_above_50dma=60.0,
    )


def _dates(weeks: int = 30) -> list[date]:
    return [START + timedelta(days=week * 7) for week in range(weeks)]


def _long_screen_hits(*, invert_throttle: bool, throttle_penalty: float = 0.0) -> list[LongScreenObservation]:
    tickers = [f"T{index:02d}" for index in range(12)]
    rows: list[LongScreenObservation] = []
    for week, as_of in enumerate(_dates()):
        throttle_week = week % 2 == 1
        vol = 0.12 + (week % 5) * 0.004
        for index, ticker in enumerate(tickers):
            score = 66 + index
            realized = 0.4 + index * 0.05
            if throttle_week:
                realized = -1.2 - index * 0.04 if invert_throttle else realized
                realized -= throttle_penalty
            rows.append(_hit(as_of, ticker, realized=realized, score=score, vol=vol))
    return rows


def test_long_screen_parser_keeps_only_long_biased_scanner_hits():
    kept = long_screen_from_row(
        {
            "signal_id": "s1",
            "ticker": "aapl",
            "created_at": "2026-03-01T12:00:00+00:00",
            "realized_return_pct": 2.5,
            "score": 72,
            "recommendation_label": "Buy",
            "strategy_family": "long_term_6m",
        }
    )
    dropped_label = long_screen_from_row(
        {
            "signal_id": "s2",
            "ticker": "msft",
            "created_at": "2026-03-01T12:00:00+00:00",
            "realized_return_pct": 2.5,
            "score": 80,
            "recommendation_label": "Hold",
            "strategy_family": "long_term_6m",
        }
    )
    dropped_score = long_screen_from_row(
        {
            "signal_id": "s3",
            "ticker": "nvda",
            "created_at": "2026-03-01T12:00:00+00:00",
            "realized_return_pct": 2.5,
            "score": 60,
            "recommendation_label": "Buy",
            "strategy_family": "long_term_6m",
        }
    )

    assert kept is not None
    assert kept.ticker == "AAPL"
    assert dropped_label is None
    assert dropped_score is None


def test_credit_throttle_reports_success_when_widening_days_are_the_bad_days():
    dates = _dates()
    panel = _panel(dates, lambda as_of: "throttle" if ((as_of - START).days // 7) % 2 == 1 else "full")
    payload = CreditRegimeEvalService(
        hits=_long_screen_hits(invert_throttle=True, throttle_penalty=0.4)
    ).evaluate_panel(panel)

    assert payload["status"] == "research_only"
    assert payload["deployment_guard"]["live_recommendation_changes"] is False
    assert payload["deployment_guard"]["is_stock_picker"] is False
    assert payload["pre_registration"]["gate_is_fitted"] is False
    assert payload["latest_view"]["applied_impact"] == 0
    assert payload["latest_view"]["mode"] == "shadow"
    assert payload["verdict"]["live_surface_changed"] is False
    assert payload["verdict"]["breadth_keep_shipped"] is False
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["eligible_gate_folds"] == 3
    assert payload["verdict"]["winning_primary_metrics"]
    assert ICE_REDISTRIBUTION_NOTICE in payload["ice_redistribution_notice"]
    assert THROTTLE_WEIGHT == 0.50


def test_credit_throttle_fails_when_widening_days_are_not_worse():
    dates = _dates()
    panel = _panel(dates, lambda as_of: "throttle" if ((as_of - START).days // 7) % 2 == 1 else "full")
    payload = CreditRegimeEvalService(hits=_long_screen_hits(invert_throttle=False)).evaluate_panel(panel)

    assert payload["deployment_guard"]["automatic_config_changes"] is False
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["winning_primary_metrics"] == []


def test_eval_aborts_when_series_history_is_data_blocked():
    dates = _dates(8)
    panel = _panel(dates, lambda _as_of: "full")
    panel = CreditPanel(
        recipe=panel.recipe,
        rows=panel.rows,
        source="fixture",
        hy_count=80,
        ig_count=80,
        history_sessions=80,
        coverage={**panel.coverage, "data_blocked": True, "hy_count": 80},
        abort_reasons=("80 HY OAS observations are available; 252 are required. FAIL data-blocked.",),
    )
    payload = CreditRegimeEvalService(hits=_long_screen_hits(invert_throttle=True)[:40]).evaluate_panel(panel)

    assert payload["verdict"]["outcome"] == "aborted"
    assert any("data-blocked" in reason for reason in payload["verdict"]["abort_reasons"])


def test_nested_model_flags_redundancy_with_equity_vol():
    dates = _dates()

    def vol_for_date(as_of: date) -> float:
        return 0.10 + ((as_of - START).days % 21) / 100

    hits: list[LongScreenObservation] = []
    for as_of in dates:
        vol = vol_for_date(as_of)
        for index in range(12):
            hits.append(
                _hit(
                    as_of,
                    f"T{index:02d}",
                    realized=vol * 10,
                    score=70 + index,
                    vol=vol,
                )
            )
    panel = _panel(dates, lambda _as_of: "full", vol_for_date=vol_for_date, credit_from_vol=True)
    payload = CreditRegimeEvalService(hits=hits).evaluate_panel(panel)

    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["credit_redundant_with_vol_or_breadth"] is True


def test_breadth_keep_comparator_is_available_when_a_status_map_is_supplied():
    dates = _dates()
    panel = _panel(dates, lambda as_of: "throttle" if ((as_of - START).days // 7) % 2 == 1 else "full")
    breadth = {as_of: "open" if ((as_of - START).days // 7) % 2 == 0 else "closed" for as_of in dates}
    payload = CreditRegimeEvalService(
        hits=_long_screen_hits(invert_throttle=True, throttle_penalty=0.4)
    ).evaluate_panel(panel, breadth_status_by_date=breadth)

    assert payload["verdict"]["breadth_keep_shipped"] is True
    assert payload["data_quality"]["breadth_keep_shipped"] is True
    assert payload["gate_fold_results"][0]["breadth_gated"] is not None or not payload["gate_fold_results"][0]["eligible"]
