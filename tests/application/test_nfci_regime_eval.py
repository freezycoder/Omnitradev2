from __future__ import annotations

import math
from datetime import date, timedelta

from application.nfci_regime_eval_service import (
    LongScreenObservation,
    NfciRegimeEvalService,
    long_screen_from_row,
)
from config.nfci_regime import (
    HY_MIN_SERIES_SESSIONS_HARD,
    MIN_NFCI_WEEKS_HARD,
    RELEASE_LAG_CALENDAR_DAYS,
)
from domain.scoring.nfci_regime import build_hy_keep_panel, build_nfci_panel
from providers.macro.nfci_client import HyKeepObservation, NfciObservation, NfciSeriesBundle


def _nfci_obs(week_end: date, value: float) -> NfciObservation:
    return NfciObservation(
        observation_week_end=week_end,
        release_date=week_end + timedelta(days=RELEASE_LAG_CALENDAR_DAYS),
        nfci=value,
        release_source="fixture",
    )


def _bundle(
    nfci_values: list[tuple[date, float]],
    hy_values: list[tuple[date, float, float]],
) -> NfciSeriesBundle:
    nfci_rows = tuple(_nfci_obs(week_end, value) for week_end, value in nfci_values)
    hy_rows = tuple(
        HyKeepObservation(as_of=as_of, hy_oas=hy, ig_oas=ig) for as_of, hy, ig in hy_values
    )
    return NfciSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-16T00:00:00+00:00",
        observations=nfci_rows,
        hy_observations=hy_rows,
        nfci_count=len(nfci_rows),
        hy_count=len(hy_rows),
        ig_count=len(hy_rows),
        first_release_date=nfci_rows[0].release_date if nfci_rows else None,
        last_release_date=nfci_rows[-1].release_date if nfci_rows else None,
    )


def _constant_hy_path(start: date, sessions: int, level: float = 4.0) -> list[tuple[date, float, float]]:
    return [(start + timedelta(days=index), level, 1.2) for index in range(sessions)]


def _rising_then_falling_nfci(start: date, weeks: int) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    value = -0.70
    week_end = start
    for index in range(weeks):
        phase = index % 8
        value += 0.04 if phase < 6 else -0.05
        rows.append((week_end, value))
        week_end += timedelta(days=7)
    return rows


def _hits_from_panel(
    nfci_values: list[tuple[date, float]],
    *,
    ticker_count: int = 12,
    skip_weeks: int = 20,
    invert_throttle: bool = True,
    return_from_hy: bool = False,
    hy_by_date: dict[date, float] | None = None,
    independent_returns: bool = False,
) -> list[LongScreenObservation]:
    hits: list[LongScreenObservation] = []
    for week_index, (week_end, _nfci) in enumerate(nfci_values[skip_weeks:], start=skip_weeks):
        release = week_end + timedelta(days=RELEASE_LAG_CALENDAR_DAYS)
        streak = 0
        for lookback in range(week_index, 3, -1):
            delta = nfci_values[lookback][1] - nfci_values[lookback - 4][1]
            if delta > 0:
                streak += 1
            else:
                break
        throttled = streak >= 3
        if independent_returns:
            realized = 0.35 * math.sin(2.0 * math.pi * week_index / 5.0)
        elif return_from_hy and hy_by_date is not None:
            realized = -(hy_by_date.get(release, 4.0) - 4.0) * 40.0
        elif invert_throttle:
            realized = -2.4 if throttled else 1.6 + 0.05 * (week_index % 3)
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
                    spy_realized_vol_20d=0.16 + 0.001 * (week_index % 5),
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


def test_nested_gate_reports_success_when_nfci_adds_lift_beyond_hy_keep():
    nfci_start = date(2023, 1, 6)
    hy_start = date(2023, 1, 3)
    nfci_values = _rising_then_falling_nfci(nfci_start, MIN_NFCI_WEEKS_HARD + 20)
    hy_values = _constant_hy_path(hy_start, HY_MIN_SERIES_SESSIONS_HARD + 40)
    bundle = _bundle(nfci_values, hy_values)
    hits = _hits_from_panel(nfci_values, invert_throttle=True)
    payload = NfciRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["deployment_guard"]["live_recommendation_changes"] is False
    assert payload["deployment_guard"]["is_stock_picker"] is False
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["kill_switch"] == "not_triggered"


def test_kill_switch_fires_when_nfci_is_redundant_with_hy_oas():
    nfci_start = date(2023, 1, 6)
    hy_start = date(2023, 1, 3)
    hy_values = _constant_hy_path(hy_start, HY_MIN_SERIES_SESSIONS_HARD + 80)
    nfci_values: list[tuple[date, float]] = []
    week_end = nfci_start
    for _index in range(MIN_NFCI_WEEKS_HARD + 20):
        nfci_values.append((week_end, -0.50))
        week_end += timedelta(days=7)
    bundle = _bundle(nfci_values, hy_values)
    hits = _hits_from_panel(nfci_values, independent_returns=True)
    payload = NfciRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["kill_switch"] == "kill_redundant_with_hy_oas"
    assert payload["verdict"]["nfci_redundant_with_hy_oas"] is True


def test_eval_aborts_when_hy_keep_is_missing():
    nfci_start = date(2023, 1, 6)
    nfci_values = _rising_then_falling_nfci(nfci_start, MIN_NFCI_WEEKS_HARD + 8)
    bundle = _bundle(nfci_values, [])
    hits = _hits_from_panel(nfci_values)
    payload = NfciRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert payload["verdict"]["hy_keep_available"] is False
    assert any("KEEP HY OAS" in reason for reason in payload["verdict"]["abort_reasons"])


def test_eval_aborts_when_nfci_history_is_too_short():
    nfci_values = _rising_then_falling_nfci(date(2025, 1, 3), 20)
    hy_values = _constant_hy_path(date(2024, 1, 2), HY_MIN_SERIES_SESSIONS_HARD)
    bundle = _bundle(nfci_values, hy_values)
    hits = _hits_from_panel(nfci_values, skip_weeks=8)
    payload = NfciRegimeEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert any("FAIL data-blocked" in reason for reason in payload["abort_reasons"])


def test_joined_hits_use_release_dated_nfci_not_week_end():
    nfci_values = _rising_then_falling_nfci(date(2023, 1, 6), MIN_NFCI_WEEKS_HARD)
    hy_values = _constant_hy_path(date(2023, 1, 3), HY_MIN_SERIES_SESSIONS_HARD)
    bundle = _bundle(nfci_values, hy_values)
    nfci_panel = build_nfci_panel(bundle)
    hy_panel = build_hy_keep_panel(bundle)
    week_end, value = nfci_values[-1]
    release = week_end + timedelta(days=RELEASE_LAG_CALENDAR_DAYS)
    premature = LongScreenObservation(
        signal_id="early",
        ticker="AAA",
        signal_date=week_end + timedelta(days=1),
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
    service = NfciRegimeEvalService(hits=[premature, ready])
    joined = service._with_panel_features([premature, ready], nfci_panel, hy_panel, breadth_status_by_date=None)
    assert joined[0].nfci_level != value
    assert joined[1].nfci_level == value
