from __future__ import annotations

from datetime import date, timedelta

from config.kcroro_regime import RELEASE_LAG_CALENDAR_DAYS, THROTTLE_WEIGHT
from domain.scoring.kcroro_regime import (
    build_hy_keep_panel,
    build_kcroro_panel,
    build_kcroro_regime_view,
    build_nfci_keep_panel,
    evaluate_hy_keep_gate,
    evaluate_kcroro_gate,
    evaluate_nfci_keep_gate,
)
from providers.macro.kcroro_client import (
    HyKeepObservation,
    KcroroObservation,
    KcroroSeriesBundle,
    NfciKeepObservation,
)


def _kcroro_bundle(
    rows: list[KcroroObservation],
    hy: list[HyKeepObservation] | None = None,
    nfci: list[NfciKeepObservation] | None = None,
) -> KcroroSeriesBundle:
    hy_rows = tuple(hy or ())
    nfci_rows = tuple(nfci or ())
    return KcroroSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-17T00:00:00+00:00",
        observations=tuple(rows),
        hy_observations=hy_rows,
        nfci_observations=nfci_rows,
        kcroro_count=len(rows),
        spreads_count=sum(row.spreads is not None for row in rows),
        equities_count=sum(row.equities is not None for row in rows),
        liquidity_count=sum(row.liquidity is not None for row in rows),
        fx_gold_count=sum(row.fx_gold is not None for row in rows),
        hy_count=sum(row.hy_oas is not None for row in hy_rows),
        ig_count=sum(row.ig_oas is not None for row in hy_rows),
        nfci_count=len(nfci_rows),
        first_release_date=rows[0].release_date if rows else None,
        last_release_date=rows[-1].release_date if rows else None,
    )


def _daily_path(start: date, values: list[float]) -> list[KcroroObservation]:
    rows: list[KcroroObservation] = []
    as_of = start
    for value in values:
        rows.append(
            KcroroObservation(
                observation_date=as_of,
                release_date=as_of + timedelta(days=RELEASE_LAG_CALENDAR_DAYS),
                kcroro=value,
                spreads=value,
                equities=value,
                liquidity=value,
                fx_gold=value,
                release_source="fixture",
            )
        )
        as_of += timedelta(days=1)
    return rows


def test_frozen_throttle_requires_positive_level_or_positive_20d_shock_sum():
    unknown = evaluate_kcroro_gate(kcroro=None, shock_sum_20d=0.4)
    assert unknown.status == "unknown"
    assert unknown.throttle_weight is None

    full = evaluate_kcroro_gate(kcroro=-0.10, shock_sum_20d=-0.50)
    assert full.status == "full"
    assert full.throttle_weight == 1.0

    level_hit = evaluate_kcroro_gate(kcroro=0.18, shock_sum_20d=-1.0)
    assert level_hit.status == "throttle"
    assert level_hit.throttle_weight == THROTTLE_WEIGHT

    sum_hit = evaluate_kcroro_gate(kcroro=-0.05, shock_sum_20d=0.20)
    assert sum_hit.status == "throttle"


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


def test_nfci_keep_gate_matches_discovered_nfci_gate_v1():
    almost = evaluate_nfci_keep_gate(nfci=-0.2, nfci_d4w=0.05, rising_streak=2)
    assert almost.status == "full"
    hit = evaluate_nfci_keep_gate(nfci=-0.2, nfci_d4w=0.05, rising_streak=3)
    assert hit.status == "throttle"


def test_release_date_join_does_not_use_observation_date():
    warmup = _daily_path(date(2026, 8, 10), [-0.1] * 29)
    latest = KcroroObservation(
        observation_date=date(2026, 9, 8),
        release_date=date(2026, 9, 9),
        kcroro=0.1814,
        spreads=0.02,
        equities=0.10,
        liquidity=0.01,
        fx_gold=0.05,
        release_source="alfred_initial_release",
    )
    panel = build_kcroro_panel(_kcroro_bundle([*warmup, latest]))

    before_release = panel.snapshot_on(date(2026, 9, 8))
    assert before_release is not None
    assert before_release.observation_date == date(2026, 9, 7)
    assert before_release.kcroro == -0.1

    on_release = panel.snapshot_on(date(2026, 9, 9))
    assert on_release is not None
    assert on_release.observation_date == date(2026, 9, 8)
    assert on_release.kcroro == 0.1814
    assert on_release.release_date == date(2026, 9, 9)


def test_panel_computes_20d_shock_sum_and_non_equity_ablation():
    values = [-0.2] * 20 + [0.4] * 10
    panel = build_kcroro_panel(_kcroro_bundle(_daily_path(date(2025, 1, 2), values)))
    ready = [row for row in panel.rows if row.shock_sum_20d is not None]
    assert len(ready) == len(values) - 19
    first_positive_block = [row for row in ready if row.kcroro == 0.4]
    assert first_positive_block
    assert all(row.gate.status == "throttle" for row in first_positive_block)
    assert all(row.ablation_gate.status == "throttle" for row in first_positive_block)


def test_regime_view_stays_shadow_with_zero_applied_impact_and_citation():
    panel = build_kcroro_panel(_kcroro_bundle(_daily_path(date(2025, 1, 2), [-0.1] * 25)))
    view = build_kcroro_regime_view(panel)
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.recipe_version == "kcroro-gate-v1"
    assert "Chari" in view.citation
    assert "24-12" in view.citation


def test_keep_panels_join_on_discovered_asof_and_release_date():
    start = date(2025, 1, 2)
    hy_rows = [
        HyKeepObservation(as_of=start + timedelta(days=index), hy_oas=4.0, ig_oas=1.0)
        for index in range(30)
    ]
    nfci_rows = [
        NfciKeepObservation(
            observation_week_end=start + timedelta(days=7 * index),
            release_date=start + timedelta(days=7 * index + 6),
            nfci=-0.50,
            release_source="fixture",
        )
        for index in range(8)
    ]
    bundle = _kcroro_bundle(_daily_path(start, [-0.1] * 30), hy=hy_rows, nfci=nfci_rows)
    hy_panel = build_hy_keep_panel(bundle)
    nfci_panel = build_nfci_keep_panel(bundle)
    hy_snapshot = hy_panel.snapshot_on(date(2025, 1, 15))
    assert hy_snapshot is not None
    assert hy_snapshot.as_of == date(2025, 1, 15)
    premature = nfci_panel.snapshot_on(start + timedelta(days=1))
    assert premature is None or premature.observation_week_end == start
    ready = nfci_panel.snapshot_on(start + timedelta(days=6))
    assert ready is not None
    assert ready.release_date == start + timedelta(days=6)
