from __future__ import annotations

from datetime import date, timedelta

from config.nfci_regime import PERSISTENCE_WEEKS, RELEASE_LAG_CALENDAR_DAYS, THROTTLE_WEIGHT
from domain.scoring.nfci_regime import (
    build_hy_keep_panel,
    build_nfci_panel,
    build_nfci_regime_view,
    evaluate_hy_keep_gate,
    evaluate_nfci_gate,
)
from providers.macro.nfci_client import HyKeepObservation, NfciObservation, NfciSeriesBundle


def _nfci_bundle(rows: list[NfciObservation], hy: list[HyKeepObservation] | None = None) -> NfciSeriesBundle:
    hy_rows = tuple(hy or ())
    return NfciSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-16T00:00:00+00:00",
        observations=tuple(rows),
        hy_observations=hy_rows,
        nfci_count=len(rows),
        hy_count=sum(row.hy_oas is not None for row in hy_rows),
        ig_count=sum(row.ig_oas is not None for row in hy_rows),
        first_release_date=rows[0].release_date if rows else None,
        last_release_date=rows[-1].release_date if rows else None,
    )


def _weekly_path(start: date, values: list[float]) -> list[NfciObservation]:
    rows: list[NfciObservation] = []
    week_end = start
    for value in values:
        rows.append(
            NfciObservation(
                observation_week_end=week_end,
                release_date=week_end + timedelta(days=RELEASE_LAG_CALENDAR_DAYS),
                nfci=value,
                release_source="fixture",
            )
        )
        week_end += timedelta(days=7)
    return rows


def test_persistence_throttle_requires_frozen_n_consecutive_positive_4w_changes():
    unknown = evaluate_nfci_gate(nfci=None, nfci_d4w=0.1, rising_streak=3)
    assert unknown.status == "unknown"
    assert unknown.throttle_weight is None

    almost = evaluate_nfci_gate(nfci=-0.2, nfci_d4w=0.05, rising_streak=PERSISTENCE_WEEKS - 1)
    assert almost.status == "full"
    assert almost.throttle_weight == 1.0

    hit = evaluate_nfci_gate(nfci=-0.2, nfci_d4w=0.05, rising_streak=PERSISTENCE_WEEKS)
    assert hit.status == "throttle"
    assert hit.throttle_weight == THROTTLE_WEIGHT


def test_hy_keep_gate_matches_discovered_credit_gate_v1():
    missing = evaluate_hy_keep_gate(
        hy_oas=4.0,
        hy_oas_d20_bp=None,
        hy_oas_percentile_252=90.0,
        percentile_observations=200,
    )
    assert missing.status == "unknown"

    velocity = evaluate_hy_keep_gate(
        hy_oas=4.0,
        hy_oas_d20_bp=31.0,
        hy_oas_percentile_252=10.0,
        percentile_observations=200,
    )
    assert velocity.status == "throttle"

    percentile = evaluate_hy_keep_gate(
        hy_oas=6.0,
        hy_oas_d20_bp=1.0,
        hy_oas_percentile_252=80.0,
        percentile_observations=200,
    )
    assert percentile.status == "throttle"

    full = evaluate_hy_keep_gate(
        hy_oas=4.0,
        hy_oas_d20_bp=10.0,
        hy_oas_percentile_252=40.0,
        percentile_observations=200,
    )
    assert full.status == "full"


def test_release_date_join_does_not_use_week_end_label():
    # Verified 2026-09-16: obs 2026-09-04 = -0.564, updated 2026-09-10.
    prior = NfciObservation(
        observation_week_end=date(2026, 8, 28),
        release_date=date(2026, 9, 3),
        nfci=-0.50,
        release_source="fixture",
    )
    latest = NfciObservation(
        observation_week_end=date(2026, 9, 4),
        release_date=date(2026, 9, 10),
        nfci=-0.564,
        release_source="alfred_initial_release",
    )
    warmup = _weekly_path(date(2026, 6, 5), [-0.4 + 0.01 * index for index in range(12)])
    panel = build_nfci_panel(_nfci_bundle([*warmup, prior, latest]))

    before_release = panel.snapshot_on(date(2026, 9, 5))
    assert before_release is not None
    assert before_release.observation_week_end == date(2026, 8, 28)
    assert before_release.nfci == -0.50

    on_release = panel.snapshot_on(date(2026, 9, 10))
    assert on_release is not None
    assert on_release.observation_week_end == date(2026, 9, 4)
    assert on_release.nfci == -0.564
    assert on_release.release_date == date(2026, 9, 10)


def test_panel_computes_4w_delta_and_rising_streak_on_weekly_prints():
    # 4 weeks of +0.05 then 3 more rising weeks → streak hits N=3 on the 7th delta-ready week.
    values = [-0.60]
    for _ in range(10):
        values.append(values[-1] + 0.05)
    panel = build_nfci_panel(_nfci_bundle(_weekly_path(date(2025, 1, 3), values)))
    ready = [row for row in panel.rows if row.nfci_d4w is not None]
    assert ready
    first_delta = ready[0]
    assert first_delta.nfci_d4w is not None
    assert first_delta.nfci_d4w == round(0.05 * 4, 10) or abs(first_delta.nfci_d4w - 0.20) < 1e-9
    throttled = [row for row in panel.rows if row.gate.status == "throttle"]
    assert throttled
    assert all(row.rising_streak >= PERSISTENCE_WEEKS for row in throttled)


def test_regime_view_stays_shadow_with_zero_applied_impact():
    values = [-0.4 + 0.01 * index for index in range(16)]
    panel = build_nfci_panel(_nfci_bundle(_weekly_path(date(2025, 1, 3), values)))
    view = build_nfci_regime_view(panel)
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.recipe_version == "nfci-gate-v1"


def test_hy_keep_panel_uses_observation_date_asof_join():
    start = date(2025, 1, 2)
    hy_rows = [
        HyKeepObservation(as_of=start + timedelta(days=index), hy_oas=4.0, ig_oas=1.0)
        for index in range(30)
    ]
    panel = build_hy_keep_panel(_nfci_bundle(_weekly_path(date(2025, 1, 3), [-0.4] * 8), hy=hy_rows))
    snapshot = panel.snapshot_on(date(2025, 1, 15))
    assert snapshot is not None
    assert snapshot.as_of == date(2025, 1, 15)
    weekend = panel.snapshot_on(date(2025, 1, 18))  # Saturday after Friday 17th
    assert weekend is not None
    assert weekend.as_of <= date(2025, 1, 18)
