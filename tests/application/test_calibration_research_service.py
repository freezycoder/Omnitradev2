from __future__ import annotations

from datetime import date, timedelta

import pytest

from application.calibration_research_service import (
    CalibrationObservation,
    CalibrationResearchService,
)


START = date(2026, 1, 1)


def _observation(
    index: int,
    *,
    signal_date: date,
    strategy: str = "short_term_swing",
    score: float = 75,
    return_pct: float = 1.0,
    confidence: str = "High",
    regime: str = "MOMENTUM",
) -> CalibrationObservation:
    return CalibrationObservation(
        signal_id=f"signal-{index}",
        ticker=("AAPL", "MSFT", "NVDA", "AMZN")[index % 4],
        strategy_family=strategy,
        score=score,
        recommendation_label="Strong Setup",
        confidence_band=confidence,
        regime=regime,
        source_quality="live",
        signal_date=signal_date,
        evaluated_date=signal_date + timedelta(days=5),
        realized_return_pct=return_pct,
    )


@pytest.fixture
def broad_observations() -> list[CalibrationObservation]:
    observations: list[CalibrationObservation] = []
    for date_index in range(30):
        signal_date = START + timedelta(days=date_index * 4)
        for ticker_index in range(4):
            index = date_index * 4 + ticker_index
            observations.append(
                _observation(
                    index,
                    signal_date=signal_date,
                    score=(58, 64, 72, 82)[ticker_index],
                    return_pct=(0.6, 0.9, 1.2, -0.2)[ticker_index],
                    confidence=("Moderate", "Moderate", "High", "High")[
                        ticker_index
                    ],
                )
            )
    return observations


def _row(payload, *, threshold: int, cost_bps: int):
    return next(
        row
        for row in payload["threshold_sensitivity"]
        if row["strategy_family"] == "short_term_swing"
        and row["regime"] == "ALL"
        and row["min_score"] == threshold
        and row["cost_bps"] == cost_bps
    )


def test_cost_scenarios_apply_basis_points_to_each_trade(
    broad_observations,
) -> None:
    payload = CalibrationResearchService(
        observations=broad_observations,
        bootstrap_iterations=40,
    ).build_payload()

    five_bps = _row(payload, threshold=70, cost_bps=5)
    twenty_bps = _row(payload, threshold=70, cost_bps=20)

    assert five_bps["oos_net_expectancy_pct"] - twenty_bps[
        "oos_net_expectancy_pct"
    ] == pytest.approx(0.15)
    assert five_bps["oos_gross_expectancy_pct"] == twenty_bps[
        "oos_gross_expectancy_pct"
    ]


def test_walk_forward_uses_calendar_embargo_and_has_no_overlap(
    broad_observations,
) -> None:
    payload = CalibrationResearchService(
        observations=broad_observations,
        bootstrap_iterations=40,
    ).build_payload()

    folds = payload["walk_forward_folds"]

    assert len(folds) == 3
    assert all(fold["eligible"] for fold in folds)
    for fold in folds:
        training_end = date.fromisoformat(fold["training_end"])
        validation_start = date.fromisoformat(fold["validation_start"])
        assert validation_start - training_end == timedelta(days=15)


def test_clustered_interval_is_deterministic_and_research_only(
    broad_observations,
) -> None:
    first = CalibrationResearchService(
        observations=broad_observations,
        bootstrap_iterations=60,
        bootstrap_seed=9,
    ).build_payload()
    second = CalibrationResearchService(
        observations=broad_observations,
        bootstrap_iterations=60,
        bootstrap_seed=9,
    ).build_payload()

    assert _row(first, threshold=70, cost_bps=10)[
        "confidence_interval_low_pct"
    ] == _row(second, threshold=70, cost_bps=10)["confidence_interval_low_pct"]
    assert first["status"] == "research_only"
    assert first["deployment_guard"]["automatic_config_changes"] is False
    assert all(
        comparison["deployment_status"] == "research_only_no_config_change"
        for comparison in first["current_vs_candidate"]
    )


def test_sparse_segments_are_not_promoted() -> None:
    observations = [
        _observation(
            index,
            signal_date=START + timedelta(days=index),
            return_pct=5.0,
        )
        for index in range(7)
    ]

    payload = CalibrationResearchService(
        observations=observations,
        bootstrap_iterations=40,
    ).build_payload()
    row = _row(payload, threshold=70, cost_bps=10)
    comparison = next(
        item
        for item in payload["current_vs_candidate"]
        if item["strategy_family"] == "short_term_swing"
        and item["regime"] == "ALL"
    )

    assert row["evidence_level"] == "insufficient"
    assert row["validation_basis"] == "in_sample_fallback"
    assert row["verdict"] == "insufficient"
    assert comparison["verdict"] == "insufficient"


def test_confidence_reliability_does_not_invent_probabilities(
    broad_observations,
) -> None:
    payload = CalibrationResearchService(
        observations=broad_observations,
        bootstrap_iterations=40,
    ).build_payload()
    reliability = payload["confidence_reliability"]

    assert reliability["probability_scoring_available"] is False
    assert reliability["brier_score"] is None
    assert "ordinal label" in reliability["reason"]
    assert {
        row["confidence_band"] for row in reliability["rows"]
    } == {"Moderate", "High"}


def test_sensitivity_keeps_strategy_and_regime_segments_separate(
    broad_observations,
) -> None:
    mean_reversion_day = [
        _observation(
            1000 + index,
            signal_date=START + timedelta(days=index * 4),
            strategy="short_term_day",
            regime="MEAN_REVERSION",
        )
        for index in range(30)
    ]

    payload = CalibrationResearchService(
        observations=[*broad_observations, *mean_reversion_day],
        bootstrap_iterations=40,
    ).build_payload()
    segments = {
        (row["strategy_family"], row["regime"])
        for row in payload["threshold_sensitivity"]
    }

    assert segments == {
        ("short_term_day", "ALL"),
        ("short_term_day", "MOMENTUM"),
        ("short_term_day", "MEAN_REVERSION"),
        ("short_term_swing", "ALL"),
        ("short_term_swing", "MOMENTUM"),
        ("short_term_swing", "MEAN_REVERSION"),
    }
