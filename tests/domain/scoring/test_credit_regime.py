from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from config.credit_regime import (
    CREDIT_MODE,
    PERCENTILE_THROTTLE,
    THROTTLE_WEIGHT,
    VELOCITY_WIDENING_BP,
)
from domain.scoring.credit_regime import (
    build_credit_panel,
    build_credit_regime_view,
    crisis_descriptive_overlay,
    evaluate_gate,
    lead_lag_diagnostics,
)
from providers.macro.credit_oas_client import CreditSeriesBundle, CreditSeriesObservation


def _bundle_from_values(
    hy_values: list[float],
    ig_values: list[float] | None = None,
    *,
    start: date = date(2023, 1, 3),
    source: str = "fixture",
) -> CreditSeriesBundle:
    ig_values = ig_values if ig_values is not None else [value - 1.5 for value in hy_values]
    observations = []
    current = start
    for hy_oas, ig_oas in zip(hy_values, ig_values, strict=True):
        observations.append(CreditSeriesObservation(current, hy_oas, ig_oas))
        current += timedelta(days=1)
        while current.weekday() >= 5:
            current += timedelta(days=1)
    hy_count = sum(row.hy_oas is not None for row in observations)
    return CreditSeriesBundle(
        status="available",
        source=source,
        retrieved_at="2026-09-15T00:00:00+00:00",
        observations=tuple(observations),
        hy_count=hy_count,
        ig_count=sum(row.ig_oas is not None for row in observations),
        first_date=observations[0].as_of,
        last_date=observations[-1].as_of,
        history_plan={"march_2020_in_window": observations[0].as_of <= date(2020, 3, 31)},
    )


def _spy(values: list[float], start: date = date(2023, 1, 3)) -> pd.DataFrame:
    index = []
    current = start
    for _ in values:
        index.append(pd.Timestamp(current))
        current += timedelta(days=1)
        while current.weekday() >= 5:
            current += timedelta(days=1)
    return pd.DataFrame({"Close": values}, index=pd.DatetimeIndex(index))


def test_evaluate_gate_throttles_on_frozen_velocity_or_percentile_only():
    full = evaluate_gate(
        hy_oas=2.70,
        hy_oas_d20_bp=10.0,
        hy_oas_percentile_252=40.0,
        percentile_observations=200,
    )
    velocity = evaluate_gate(
        hy_oas=3.10,
        hy_oas_d20_bp=VELOCITY_WIDENING_BP + 1,
        hy_oas_percentile_252=40.0,
        percentile_observations=200,
    )
    percentile = evaluate_gate(
        hy_oas=3.80,
        hy_oas_d20_bp=10.0,
        hy_oas_percentile_252=PERCENTILE_THROTTLE,
        percentile_observations=200,
    )
    unknown = evaluate_gate(
        hy_oas=2.70,
        hy_oas_d20_bp=None,
        hy_oas_percentile_252=90.0,
        percentile_observations=200,
    )
    warmup_percentile_ignored = evaluate_gate(
        hy_oas=4.00,
        hy_oas_d20_bp=5.0,
        hy_oas_percentile_252=99.0,
        percentile_observations=20,
    )

    assert full.status == "full"
    assert full.throttle_weight == 1.0
    assert velocity.status == "throttle"
    assert velocity.throttle_weight == THROTTLE_WEIGHT
    assert percentile.status == "throttle"
    assert unknown.status == "unknown"
    assert unknown.throttle_weight is None
    assert warmup_percentile_ignored.status == "full"
    assert VELOCITY_WIDENING_BP == 30.0
    assert PERCENTILE_THROTTLE == 80.0


def test_panel_computes_level_velocity_weekly_gap_and_keeps_gap_out_of_the_gate():
    hy = [3.0] * 40 + [3.40]  # last print +40 bp vs 20 sessions back
    ig = [1.2] * 41
    panel = build_credit_panel(_bundle_from_values(hy, ig))
    latest = panel.rows[-1]

    assert latest.hy_oas == pytest.approx(3.40)
    assert latest.ig_oas == pytest.approx(1.2)
    assert latest.hy_ig_gap == pytest.approx(2.20)
    assert latest.hy_oas_d20_bp == pytest.approx(40.0)
    assert latest.hy_oas_d5_bp == pytest.approx(40.0)
    assert latest.gate.status == "throttle"
    assert "HY−IG" not in " ".join(latest.gate.reasons)
    assert "Weekly" not in " ".join(latest.gate.reasons)


def test_causal_percentile_does_not_use_future_prints():
    hy = [3.0] * 180 + [5.0] + [3.0] * 10
    panel = build_credit_panel(_bundle_from_values(hy))
    spike = next(row for row in panel.rows if row.hy_oas == 5.0)
    after = [row for row in panel.rows if row.as_of > spike.as_of]

    assert spike.hy_oas_percentile_252 == 100.0
    assert spike.gate.status == "throttle"
    assert after[0].hy_oas == 3.0
    assert after[0].hy_oas_percentile_252 is None or after[0].hy_oas_percentile_252 < 80.0


def test_short_history_is_data_blocked_and_applied_impact_stays_zero():
    panel = build_credit_panel(_bundle_from_values([3.0] * 80))
    view = build_credit_regime_view(panel)

    assert panel.coverage["data_blocked"] is True
    assert any("data-blocked" in reason for reason in panel.abort_reasons)
    assert view.mode == CREDIT_MODE
    assert view.applied_impact == 0


def test_march_2020_overlay_is_descriptive_and_not_a_tune_target():
    recent = build_credit_panel(_bundle_from_values([3.0] * 260, start=date(2023, 9, 15)))
    crisis = build_credit_panel(_bundle_from_values([4.0] * 30 + [10.0] + [8.0] * 10, start=date(2020, 2, 3)))

    recent_overlay = crisis_descriptive_overlay(recent)
    crisis_overlay = crisis_descriptive_overlay(crisis)

    assert recent_overlay["status"] == "not_in_window"
    assert crisis_overlay["status"] == "descriptive_only"
    assert crisis_overlay["tune_target"] is False
    assert crisis_overlay["peak_hy_oas"] == 10.0


def test_lead_lag_is_descriptive_and_requires_spy():
    hy = [3.0 + index * 0.01 for index in range(80)]
    spy = [400 - index * 0.4 for index in range(80)]
    panel = build_credit_panel(_bundle_from_values(hy), spy_history=_spy(spy))
    diagnostics = lead_lag_diagnostics(panel)

    assert diagnostics["status"] == "available"
    assert 0 in diagnostics["offsets"]
    assert "not used to retune" in diagnostics["interpretation"]
    assert any(row["oas_lead_sessions"] == 0 for row in diagnostics["correlations"])
