from __future__ import annotations

import math
from datetime import date, timedelta

from application.stfm_funding_liquidity_eval_service import (
    LongScreenObservation,
    StfmFundingLiquidityEvalService,
    long_screen_from_row,
)
from config.stfm_funding_liquidity import (
    DAILY_RELEASE_LAG_CALENDAR_DAYS,
    HY_MIN_SERIES_SESSIONS_HARD,
    MIN_NFCI_WEEKS_HARD,
    MIN_STFM_SESSIONS_HARD,
    MMF_RELEASE_LAG_CALENDAR_DAYS,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_EFFR,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    NFCI_RELEASE_LAG_CALENDAR_DAYS,
)
from providers.macro.ofr_stfm_client import (
    HyKeepObservation,
    NfciKeepObservation,
    OfrPoint,
    StfmSeriesBundle,
)


def _weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _point(mnemonic: str, observation: date, value: float) -> OfrPoint:
    lag = MMF_RELEASE_LAG_CALENDAR_DAYS if mnemonic == MNEMONIC_MMF_TOTAL else DAILY_RELEASE_LAG_CALENDAR_DAYS
    return OfrPoint(
        observation_date=observation,
        release_date=observation + timedelta(days=lag),
        value=value,
        mnemonic=mnemonic,
    )


def _bundle(
    days: list[date],
    *,
    dvp_values: list[float],
    gcf_values: list[float],
    sofr_values: list[float],
    effr_values: list[float],
    hy_level: float = 4.0,
    hy_spikes: set[date] | None = None,
    nfci_level: float = -0.50,
) -> StfmSeriesBundle:
    mmf_months = []
    month_end = date(days[0].year, days[0].month, 1) - timedelta(days=1)
    for _ in range(30):
        mmf_months.append(_point(MNEMONIC_MMF_TOTAL, month_end, 8e12))
        month_end = date(month_end.year, month_end.month, 1) - timedelta(days=1)
    mmf_months.reverse()
    hy_spikes = hy_spikes or set()
    hy_rows = []
    running = hy_level
    for as_of in days:
        if as_of in hy_spikes:
            running = hy_level + 0.80
        else:
            running = hy_level
        hy_rows.append(HyKeepObservation(as_of=as_of, hy_oas=running, ig_oas=1.2))
    nfci_rows = []
    week_end = days[0] - timedelta(days=days[0].weekday() + 3)
    for _ in range(MIN_NFCI_WEEKS_HARD + 8):
        nfci_rows.append(
            NfciKeepObservation(
                observation_week_end=week_end,
                release_date=week_end + timedelta(days=NFCI_RELEASE_LAG_CALENDAR_DAYS),
                nfci=nfci_level,
                release_source="fixture",
            )
        )
        week_end += timedelta(days=7)
        nfci_level -= 0.002
    return StfmSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-17T00:00:00+00:00",
        series={
            MNEMONIC_DVP_VOLUME: tuple(
                _point(MNEMONIC_DVP_VOLUME, day, value) for day, value in zip(days, dvp_values)
            ),
            MNEMONIC_GCF_VOLUME: tuple(
                _point(MNEMONIC_GCF_VOLUME, day, value) for day, value in zip(days, gcf_values)
            ),
            MNEMONIC_SOFR: tuple(_point(MNEMONIC_SOFR, day, value) for day, value in zip(days, sofr_values)),
            MNEMONIC_EFFR: tuple(_point(MNEMONIC_EFFR, day, value) for day, value in zip(days, effr_values)),
            MNEMONIC_MMF_TOTAL: tuple(mmf_months),
        },
        hy_observations=tuple(hy_rows),
        nfci_observations=tuple(nfci_rows),
        history_plan={"hy_count": len(hy_rows), "nfci_count": len(nfci_rows)},
    )


def _hits_for_days(
    days: list[date],
    realized_by_day: dict[date, float],
    *,
    ticker_count: int = 12,
) -> list[LongScreenObservation]:
    hits: list[LongScreenObservation] = []
    for day in days:
        release = day + timedelta(days=DAILY_RELEASE_LAG_CALENDAR_DAYS)
        realized = realized_by_day.get(day)
        if realized is None:
            continue
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
                    spy_realized_vol_20d=0.16 + 0.001 * (ticker_index % 5),
                )
            )
    return hits


def _success_paths() -> tuple[StfmSeriesBundle, list[LongScreenObservation]]:
    days = _weekdays(date(2023, 1, 3), MIN_STFM_SESSIONS_HARD + 80)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    realized: dict[date, float] = {}
    joint_days: set[date] = set()
    spread_only_days: set[date] = set()
    for index, day in enumerate(days):
        volume = 1.00e12 + 2e9 * math.sin(index / 9.0)
        rate = 3.50
        realized[day] = 1.4 + 0.05 * (index % 4)
        if index >= 160 and index % 16 == 0:
            volume = 4.0e11
            rate = 3.62
            realized[day] = -2.6
            joint_days.add(day)
        elif index >= 168 and index % 16 == 8:
            rate = 3.62
            realized[day] = 2.1
            spread_only_days.add(day)
        dvp.append(volume)
        gcf.append(volume * 0.18)
        sofr.append(rate)
        effr.append(3.50)
    bundle = _bundle(
        days,
        dvp_values=dvp,
        gcf_values=gcf,
        sofr_values=sofr,
        effr_values=effr,
        hy_spikes=set(),
    )
    return bundle, _hits_for_days(days[150:], realized)


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
    short_term = long_screen_from_row(
        {
            "signal_id": "s-short",
            "ticker": "CCC",
            "strategy_family": "short_term_swing",
            "score": 80,
            "recommendation_label": "Buy",
            "created_at": "2026-01-09",
            "realized_return_pct": 1.5,
        }
    )
    assert short_term is None
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


def test_nested_gate_reports_success_when_stfm_beats_sofr_and_adds_keep_lift():
    bundle, hits = _success_paths()
    payload = StfmFundingLiquidityEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["deployment_guard"]["live_recommendation_changes"] is False
    assert payload["deployment_guard"]["is_stock_picker"] is False
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["verdict"]["nfci_keep_available"] is True
    assert payload["verdict"]["roro_ingest_v1"] is False
    assert payload["verdict"]["outcome"] == "success"
    assert payload["verdict"]["kill_switch"] == "not_triggered"


def test_kill_switch_fires_when_volumes_mmf_add_nothing_beyond_sofr():
    days = _weekdays(date(2023, 1, 3), MIN_STFM_SESSIONS_HARD + 80)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    realized: dict[date, float] = {}
    for index, day in enumerate(days):
        # Strictly rising volumes keep causal z-scores positive, so the joint
        # flag never fires. SOFR and EFFR move together, so the spread control
        # is inert too. Volumes/MMF therefore cannot beat SOFR-only.
        volume = 1.00e12 + 1e8 * index
        realized[day] = 0.35 * math.sin(2.0 * math.pi * index / 5.0)
        dvp.append(volume)
        gcf.append(volume * 0.18)
        sofr.append(3.50 + 0.01 * (index % 3))
        effr.append(3.50 + 0.01 * (index % 3))
    bundle = _bundle(days, dvp_values=dvp, gcf_values=gcf, sofr_values=sofr, effr_values=effr)
    hits = _hits_for_days(days[150:], realized)
    payload = StfmFundingLiquidityEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["data_quality"]["stfm_throttle_hits"] == 0
    assert payload["data_quality"]["sofr_throttle_hits"] == 0
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["kill_switch"] in {
        "kill_sofr_only",
        "kill_no_incremental_lift",
    }


def test_kill_switch_fires_when_stfm_is_redundant_with_hy_nfci():
    days = _weekdays(date(2023, 1, 3), MIN_STFM_SESSIONS_HARD + 80)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    realized: dict[date, float] = {}
    for index, day in enumerate(days):
        volume = 1.00e12 + 1e8 * index
        realized[day] = 1.3
        dvp.append(volume)
        gcf.append(volume * 0.18)
        sofr.append(3.50)
        effr.append(3.50)
    hy_rows = []
    for index, as_of in enumerate(days):
        level = 4.0 + (0.80 if index >= 160 and index % 18 == 0 else 0.0)
        if index >= 160 and index % 18 == 0:
            realized[as_of] = -2.4
        hy_rows.append(HyKeepObservation(as_of=as_of, hy_oas=level, ig_oas=1.2))
    bundle = _bundle(days, dvp_values=dvp, gcf_values=gcf, sofr_values=sofr, effr_values=effr)
    bundle = StfmSeriesBundle(
        status=bundle.status,
        source=bundle.source,
        retrieved_at=bundle.retrieved_at,
        series=bundle.series,
        hy_observations=tuple(hy_rows),
        nfci_observations=bundle.nfci_observations,
        history_plan=bundle.history_plan,
    )
    hits = _hits_for_days(days[150:], realized)
    payload = StfmFundingLiquidityEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["hy_keep_available"] is True
    assert payload["data_quality"]["stfm_throttle_hits"] == 0
    assert payload["verdict"]["outcome"] == "fail"
    assert payload["verdict"]["kill_switch"] in {
        "kill_redundant_with_hy_nfci",
        "kill_no_incremental_lift",
    }


def test_eval_aborts_when_keep_comparators_are_missing():
    days = _weekdays(date(2023, 1, 3), MIN_STFM_SESSIONS_HARD + 20)
    values = [1e12 + 1e9 * math.sin(index / 8.0) for index in range(len(days))]
    rates = [3.5 for _ in days]
    bundle = _bundle(days, dvp_values=values, gcf_values=values, sofr_values=rates, effr_values=rates)
    bundle = StfmSeriesBundle(
        status=bundle.status,
        source=bundle.source,
        retrieved_at=bundle.retrieved_at,
        series=bundle.series,
        hy_observations=(),
        nfci_observations=(),
    )
    realized = {day: 1.0 for day in days[150:]}
    hits = _hits_for_days(days[150:], realized)
    payload = StfmFundingLiquidityEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert payload["verdict"]["hy_keep_available"] is False


def test_eval_aborts_when_stfm_history_is_too_short():
    days = _weekdays(date(2025, 1, 2), 40)
    values = [1e12 for _ in days]
    rates = [3.5 for _ in days]
    hy_days = _weekdays(date(2024, 1, 2), HY_MIN_SERIES_SESSIONS_HARD)
    bundle = _bundle(days, dvp_values=values, gcf_values=values, sofr_values=rates, effr_values=rates)
    extra_hy = [
        HyKeepObservation(as_of=as_of, hy_oas=4.0, ig_oas=1.2)
        for as_of in hy_days
    ]
    bundle = StfmSeriesBundle(
        status=bundle.status,
        source=bundle.source,
        retrieved_at=bundle.retrieved_at,
        series=bundle.series,
        hy_observations=tuple(extra_hy),
        nfci_observations=bundle.nfci_observations,
    )
    hits = _hits_for_days(days, {day: 1.0 for day in days})
    payload = StfmFundingLiquidityEvalService(hits=hits).evaluate_bundle(bundle)
    assert payload["verdict"]["outcome"] == "aborted"
    assert any("FAIL data-blocked" in reason for reason in payload["abort_reasons"])
