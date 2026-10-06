from __future__ import annotations

import math
from datetime import date, timedelta

from application.kcroro_regime_eval_service import (
    KcroroRegimeEvalService,
    LongScreenObservation,
    long_screen_from_row,
)
from config.kcroro_regime import (
    HY_MIN_SERIES_SESSIONS_HARD,
    MIN_KCRORO_SESSIONS_HARD,
    MIN_NFCI_WEEKS_HARD,
    NFCI_RELEASE_LAG_CALENDAR_DAYS,
    RELEASE_LAG_CALENDAR_DAYS,
)
from domain.scoring.kcroro_regime import build_hy_keep_panel, build_kcroro_panel, build_nfci_keep_panel
from providers.macro.kcroro_client import (
    HyKeepObservation,
    KcroroObservation,
    KcroroSeriesBundle,
    NfciKeepObservation,
)


def _kcroro_obs(
    as_of: date,
    value: float,
    *,
    spreads: float | None = None,
    equities: float | None = None,
    liquidity: float | None = None,
    fx_gold: float | None = None,
) -> KcroroObservation:
    filled = value if spreads is None else spreads
    return KcroroObservation(
        observation_date=as_of,
        release_date=as_of + timedelta(days=RELEASE_LAG_CALENDAR_DAYS),
        kcroro=value,
        spreads=filled if spreads is None else spreads,
        equities=value if equities is None else equities,
        liquidity=filled if liquidity is None else liquidity,
        fx_gold=filled if fx_gold is None else fx_gold,
        release_source="fixture",
    )


def _bundle(
    kcroro_values: list[tuple[date, float, float, float, float, float]],
    hy_values: list[tuple[date, float, float]],
    nfci_values: list[tuple[date, float]],
) -> KcroroSeriesBundle:
    kcroro_rows = tuple(
        _kcroro_obs(as_of, value, spreads=spreads, equities=equities, liquidity=liquidity, fx_gold=fx_gold)
        for as_of, value, spreads, equities, liquidity, fx_gold in kcroro_values
    )
    hy_rows = tuple(
        HyKeepObservation(as_of=as_of, hy_oas=hy, ig_oas=ig) for as_of, hy, ig in hy_values
    )
    nfci_rows = tuple(
        NfciKeepObservation(
            observation_week_end=week_end,
            release_date=week_end + timedelta(days=NFCI_RELEASE_LAG_CALENDAR_DAYS),
            nfci=value,
            release_source="fixture",
        )
        for week_end, value in nfci_values
    )
    return KcroroSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-17T00:00:00+00:00",
        observations=kcroro_rows,
        hy_observations=hy_rows,
        nfci_observations=nfci_rows,
        kcroro_count=len(kcroro_rows),
        spreads_count=sum(row.spreads is not None for row in kcroro_rows),
        equities_count=sum(row.equities is not None for row in kcroro_rows),
        liquidity_count=sum(row.liquidity is not None for row in kcroro_rows),
        fx_gold_count=sum(row.fx_gold is not None for row in kcroro_rows),
        hy_count=len(hy_rows),
        ig_count=len(hy_rows),
        nfci_count=len(nfci_rows),
        first_release_date=kcroro_rows[0].release_date if kcroro_rows else None,
        last_release_date=kcroro_rows[-1].release_date if kcroro_rows else None,
    )


def _constant_hy_path(start: date, sessions: int, level: float = 4.0) -> list[tuple[date, float, float]]:
    return [(start + timedelta(days=index), level, 1.2) for index in range(sessions)]


def _constant_nfci_path(start: date, weeks: int, level: float = -0.50) -> list[tuple[date, float]]:
    return [(start + timedelta(days=7 * index), level) for index in range(weeks)]


def _alternating_kcroro_path(
    start: date,
    sessions: int,
    *,
    equity_only: bool = False,
    constant: float | None = None,
) -> list[tuple[date, float, float, float, float, float]]:
    rows: list[tuple[date, float, float, float, float, float]] = []
    for index in range(sessions):
        as_of = start + timedelta(days=index)
        if constant is not None:
            value = constant
        else:
            value = 0.40 if (index // 25) % 2 == 1 else -0.40
        if equity_only:
            rows.append((as_of, value, 0.0, value, 0.0, 0.0))
        else:
            rows.append((as_of, value, value, value, value, value))
    return rows


def _hits_from_kcroro(
    kcroro_values: list[tuple[date, float, float, float, float, float]],
    *,
    ticker_count: int = 12,
    skip: int = 40,
    invert_throttle: bool = True,
    independent_returns: bool = False,
) -> list[LongScreenObservation]:
    hits: list[LongScreenObservation] = []
    for index, (as_of, value, _spreads, _equities, _liquidity, _fx) in enumerate(kcroro_values[skip:], start=skip):
        release = as_of + timedelta(days=RELEASE_LAG_CALENDAR_DAYS)
        window = [item[1] for item in kcroro_values[index + 1 - 20 : index + 1]]
        shock_sum = sum(window) if len(window) == 20 else 0.0
        throttled = value > 0 or shock_sum > 0
        if independent_returns:
            realized = 0.35 * math.sin(2.0 * math.pi * index / 7.0)
        elif invert_throttle:
            realized = -2.4 if throttled else 1.6 + 0.05 * (index % 3)
        else:
            realized = 1.2 if throttled else -0.4
        for ticker_index in range(ticker_count):
            hits.append(
                LongScreenObservation(
                    signal_id=f"{release.isoformat()}-{ticker_index}",
                    ticker=f"T{ticker_index:02d}",
                    signal_date=release,
                    realized_return_pct=realized,
                    long_term_score=80.0,
                    recommendation_label="Buy",
                    strategy_family="long_term_3m",
                    spy_realized_vol_20d=0.16 + 0.001 * (index % 5),
                )
            )
    return hits


def test_long_screen_parser_keeps_long_biased_resolved_rows_only():
    accepted = long_screen_from_row(
        {
            "signal_id": "s1",
            "ticker": "aaa",
            "strategy_family": "long_term_6m",
            "score": 80,
            "recommendation_label": "Buy",
            "created_at": "2026-01-09",
            "realized_return_pct": 1.5,
        }
    )
    assert accepted is not None
    assert accepted.ticker == "AAA"

    rejected = long_screen_from_row(
        {
            "signal_id": "s2",
            "ticker": "BBB",
            "strategy_family": "long_term_6m",
            "score": 80,
            "recommendation_label": "Hold",
            "created_at": "2026-01-09",
            "realized_return_pct": 1.5,
        }
    )
    assert rejected is None


def test_nested_gate_reports_success_when_roro_adds_lift_beyond_hy_and_nfci():
    start = date(2023, 1, 3)
    kcroro_values = _alternating_kcroro_path(start, MIN_KCRORO_SESSIONS_HARD + 40)
    hy_values = _constant_hy_path(start, HY_MIN_SERIES_SESSIONS_HARD + 40)
    nfci_values = _constant_nfci_path(start, MIN_NFCI_WEEKS_HARD + 8)
    bundle = _bundle(kcroro_values, hy_values, nfci_values)
    hits = _hits_from_kcroro(kcroro_values, invert_throttle=True)
    payload = KcroroRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["deployment_guard"]["live_recommendation_changes"] is False
    assert payload["deployment_guard"]["is_stock_picker"] is False
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["verdict"]["nfci_keep_available"] is True
    assert payload["verdict"]["ablation_available"] is True
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["kill_switch"] == "not_triggered"
    assert "Chari" in payload["citation"]


def test_kill_switch_fires_when_roro_is_redundant_with_hy_and_nfci():
    start = date(2023, 1, 3)
    kcroro_values = _alternating_kcroro_path(start, MIN_KCRORO_SESSIONS_HARD + 40, constant=-0.10)
    hy_values = _constant_hy_path(start, HY_MIN_SERIES_SESSIONS_HARD + 40)
    nfci_values = _constant_nfci_path(start, MIN_NFCI_WEEKS_HARD + 8)
    bundle = _bundle(kcroro_values, hy_values, nfci_values)
    hits = _hits_from_kcroro(kcroro_values, independent_returns=True)
    payload = KcroroRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["verdict"]["nfci_keep_available"] is True
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["kill_switch"] == "kill_redundant_with_hy_nfci"
    assert payload["verdict"]["kcroro_redundant_with_hy_nfci"] is True


def test_kill_switch_fires_when_lift_is_only_from_equity_subindex():
    start = date(2023, 1, 3)
    kcroro_values = _alternating_kcroro_path(
        start,
        MIN_KCRORO_SESSIONS_HARD + 40,
        equity_only=True,
    )
    hy_values = _constant_hy_path(start, HY_MIN_SERIES_SESSIONS_HARD + 40)
    nfci_values = _constant_nfci_path(start, MIN_NFCI_WEEKS_HARD + 8)
    bundle = _bundle(kcroro_values, hy_values, nfci_values)
    hits = _hits_from_kcroro(kcroro_values, invert_throttle=True)
    payload = KcroroRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["ablation_available"] is True
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["kill_switch"] == "kill_equity_leg_circular"
    assert payload["verdict"]["ablation_has_lift"] is False


def test_eval_aborts_when_keep_comparators_are_missing():
    start = date(2023, 1, 3)
    kcroro_values = _alternating_kcroro_path(start, MIN_KCRORO_SESSIONS_HARD + 8)
    bundle = _bundle(kcroro_values, [], [])
    hits = _hits_from_kcroro(kcroro_values)
    payload = KcroroRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert payload["verdict"]["hy_keep_available"] is False
    assert any("KEEP HY OAS" in reason for reason in payload["verdict"]["abort_reasons"])


def test_eval_aborts_when_kcroro_history_is_too_short():
    start = date(2025, 1, 2)
    kcroro_values = _alternating_kcroro_path(start, 40)
    hy_values = _constant_hy_path(start, HY_MIN_SERIES_SESSIONS_HARD)
    nfci_values = _constant_nfci_path(start, MIN_NFCI_WEEKS_HARD)
    bundle = _bundle(kcroro_values, hy_values, nfci_values)
    hits = _hits_from_kcroro(kcroro_values, skip=20)
    payload = KcroroRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert any("FAIL data-blocked" in reason for reason in payload["abort_reasons"])


def test_joined_hits_use_release_dated_kcroro_not_observation_date():
    start = date(2023, 1, 3)
    kcroro_values = _alternating_kcroro_path(start, MIN_KCRORO_SESSIONS_HARD)
    last_as_of, _last_value, last_spreads, last_equities, last_liquidity, last_fx = kcroro_values[-1]
    kcroro_values[-1] = (last_as_of, 0.1814, last_spreads, last_equities, last_liquidity, last_fx)
    hy_values = _constant_hy_path(start, HY_MIN_SERIES_SESSIONS_HARD)
    nfci_values = _constant_nfci_path(start, MIN_NFCI_WEEKS_HARD)
    bundle = _bundle(kcroro_values, hy_values, nfci_values)
    kcroro_panel = build_kcroro_panel(bundle)
    hy_panel = build_hy_keep_panel(bundle)
    nfci_panel = build_nfci_keep_panel(bundle)
    as_of, value, *_rest = kcroro_values[-1]
    prior_as_of, prior_value, *_prior_rest = kcroro_values[-2]
    release = as_of + timedelta(days=RELEASE_LAG_CALENDAR_DAYS)
    premature = LongScreenObservation(
        signal_id="early",
        ticker="AAA",
        signal_date=as_of,
        realized_return_pct=1.0,
        long_term_score=80.0,
        recommendation_label="Buy",
        strategy_family="long_term_3m",
        spy_realized_vol_20d=0.15,
    )
    ready = LongScreenObservation(
        signal_id="ready",
        ticker="AAA",
        signal_date=release,
        realized_return_pct=1.0,
        long_term_score=80.0,
        recommendation_label="Buy",
        strategy_family="long_term_3m",
        spy_realized_vol_20d=0.15,
    )
    service = KcroroRegimeEvalService(hits=[premature, ready])
    joined = service._with_panel_features([premature, ready], kcroro_panel, hy_panel, nfci_panel)
    assert prior_as_of < as_of
    assert joined[0].kcroro_level == prior_value
    assert joined[0].kcroro_level != 0.1814
    assert joined[1].kcroro_level == value
