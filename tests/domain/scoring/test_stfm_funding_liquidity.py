from __future__ import annotations

from datetime import date, timedelta

from config.stfm_funding_liquidity import (
    DAILY_RELEASE_LAG_CALENDAR_DAYS,
    MMF_RELEASE_LAG_CALENDAR_DAYS,
    MNEMONIC_DVP_VOLUME,
    MNEMONIC_EFFR,
    MNEMONIC_GCF_VOLUME,
    MNEMONIC_MMF_TOTAL,
    MNEMONIC_SOFR,
    THROTTLE_WEIGHT,
    VOLUME_ZSCORE_DROP,
)
from domain.scoring.stfm_funding_liquidity import (
    build_stfm_panel,
    build_stfm_regime_view,
    evaluate_sofr_only_gate,
    evaluate_stfm_full_pack_gate,
)
from providers.macro.ofr_stfm_client import OfrPoint, StfmSeriesBundle


def test_full_pack_requires_joint_volume_drop_and_spread_widen():
    unknown = evaluate_stfm_full_pack_gate(dvp_z=None, gcf_z=None, sofr_effr_d5_bp=4.0)
    assert unknown.status == "unknown"
    assert unknown.throttle_weight is None

    volume_only = evaluate_stfm_full_pack_gate(
        dvp_z=VOLUME_ZSCORE_DROP,
        gcf_z=0.1,
        sofr_effr_d5_bp=1.0,
    )
    assert volume_only.status == "full"

    spread_only = evaluate_stfm_full_pack_gate(dvp_z=0.2, gcf_z=0.1, sofr_effr_d5_bp=4.0)
    assert spread_only.status == "full"

    joint = evaluate_stfm_full_pack_gate(
        dvp_z=VOLUME_ZSCORE_DROP,
        gcf_z=0.4,
        sofr_effr_d5_bp=4.0,
    )
    assert joint.status == "throttle"
    assert joint.throttle_weight == THROTTLE_WEIGHT


def test_sofr_only_control_ignores_volumes():
    missing = evaluate_sofr_only_gate(sofr_effr_d5_bp=None)
    assert missing.status == "unknown"
    hit = evaluate_sofr_only_gate(sofr_effr_d5_bp=3.1)
    assert hit.status == "throttle"
    full = evaluate_sofr_only_gate(sofr_effr_d5_bp=2.9)
    assert full.status == "full"


def _point(mnemonic: str, observation: date, value: float | None) -> OfrPoint:
    lag = MMF_RELEASE_LAG_CALENDAR_DAYS if mnemonic == MNEMONIC_MMF_TOTAL else DAILY_RELEASE_LAG_CALENDAR_DAYS
    return OfrPoint(
        observation_date=observation,
        release_date=observation + timedelta(days=lag),
        value=value,
        mnemonic=mnemonic,
    )


def _bundle_from_maps(series: dict[str, list[OfrPoint]]) -> StfmSeriesBundle:
    packed = {key: tuple(rows) for key, rows in series.items()}
    return StfmSeriesBundle(
        status="available",
        source="fixture",
        retrieved_at="2026-09-17T00:00:00+00:00",
        series=packed,
        null_counts={key: sum(row.value is None for row in rows) for key, rows in packed.items()},
    )


def test_release_date_join_does_not_use_observation_label():
    start = date(2025, 1, 2)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    mmf = [_point(MNEMONIC_MMF_TOTAL, date(2024, 12, 31), 8e12)]
    day = start
    for index in range(140):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        volume = 1e12
        dvp.append(_point(MNEMONIC_DVP_VOLUME, day, volume))
        gcf.append(_point(MNEMONIC_GCF_VOLUME, day, 2e11))
        sofr.append(_point(MNEMONIC_SOFR, day, 3.50))
        effr.append(_point(MNEMONIC_EFFR, day, 3.50))
        day += timedelta(days=1)
    panel = build_stfm_panel(
        _bundle_from_maps(
            {
                MNEMONIC_DVP_VOLUME: dvp,
                MNEMONIC_GCF_VOLUME: gcf,
                MNEMONIC_SOFR: sofr,
                MNEMONIC_EFFR: effr,
                MNEMONIC_MMF_TOTAL: mmf,
            }
        )
    )
    latest_obs = dvp[-1].observation_date
    before_release = panel.snapshot_on(latest_obs)
    assert before_release is not None
    assert before_release.observation_date < latest_obs
    on_release = panel.snapshot_on(dvp[-1].release_date)
    assert on_release is not None
    assert on_release.observation_date == latest_obs


def test_null_volume_is_not_zero_filled():
    start = date(2025, 1, 2)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    mmf = [_point(MNEMONIC_MMF_TOTAL, date(2024, 12, 31), 8e12)]
    day = start
    for index in range(30):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        value = None if index == 29 else 1e12
        dvp.append(_point(MNEMONIC_DVP_VOLUME, day, value))
        gcf.append(_point(MNEMONIC_GCF_VOLUME, day, 2e11))
        sofr.append(_point(MNEMONIC_SOFR, day, 3.50))
        effr.append(_point(MNEMONIC_EFFR, day, 3.50))
        day += timedelta(days=1)
    panel = build_stfm_panel(
        _bundle_from_maps(
            {
                MNEMONIC_DVP_VOLUME: dvp,
                MNEMONIC_GCF_VOLUME: gcf,
                MNEMONIC_SOFR: sofr,
                MNEMONIC_EFFR: effr,
                MNEMONIC_MMF_TOTAL: mmf,
            }
        )
    )
    latest = panel.rows[-1]
    assert latest.dvp_volume is None
    assert latest.dvp_z is None


def test_mmf_release_date_does_not_overwrite_daily_observation_join():
    daily_obs = date(2026, 8, 19)
    mmf_obs = date(2026, 7, 31)
    dvp = [_point(MNEMONIC_DVP_VOLUME, daily_obs, 1e12)]
    gcf = [_point(MNEMONIC_GCF_VOLUME, daily_obs, 2e11)]
    sofr = [_point(MNEMONIC_SOFR, daily_obs, 3.50)]
    effr = [_point(MNEMONIC_EFFR, daily_obs, 3.50)]
    mmf = [_point(MNEMONIC_MMF_TOTAL, mmf_obs, 8e12)]
    assert dvp[0].release_date == mmf[0].release_date
    panel = build_stfm_panel(
        _bundle_from_maps(
            {
                MNEMONIC_DVP_VOLUME: dvp,
                MNEMONIC_GCF_VOLUME: gcf,
                MNEMONIC_SOFR: sofr,
                MNEMONIC_EFFR: effr,
                MNEMONIC_MMF_TOTAL: mmf,
            }
        )
    )
    row = panel.snapshot_on(dvp[0].release_date)
    assert row is not None
    assert row.observation_date == daily_obs
    assert row.mmf_total == 8e12


def test_regime_view_stays_shadow_with_zero_applied_impact():
    start = date(2025, 1, 2)
    dvp = []
    gcf = []
    sofr = []
    effr = []
    mmf = [_point(MNEMONIC_MMF_TOTAL, date(2024, 11, 30), 8e12)]
    day = start
    for _ in range(40):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        dvp.append(_point(MNEMONIC_DVP_VOLUME, day, 1e12))
        gcf.append(_point(MNEMONIC_GCF_VOLUME, day, 2e11))
        sofr.append(_point(MNEMONIC_SOFR, day, 3.50))
        effr.append(_point(MNEMONIC_EFFR, day, 3.50))
        day += timedelta(days=1)
    panel = build_stfm_panel(
        _bundle_from_maps(
            {
                MNEMONIC_DVP_VOLUME: dvp,
                MNEMONIC_GCF_VOLUME: gcf,
                MNEMONIC_SOFR: sofr,
                MNEMONIC_EFFR: effr,
                MNEMONIC_MMF_TOTAL: mmf,
            }
        )
    )
    view = build_stfm_regime_view(panel)
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.recipe_version == "stfm-gate-v1"
