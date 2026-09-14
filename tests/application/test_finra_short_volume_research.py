from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from application.finra_short_volume_research_service import (
    FinraShortVolumeObservation,
    FinraShortVolumeResearchService,
    build_observations,
    build_walk_forward_folds,
)
from providers.market.finra_short_volume_client import FinraShortVolumeRow


def _observation(
    ticker: str,
    as_of: date,
    short_ratio: float,
    excess_5d: float,
    *,
    log_share_volume: float = 15.0,
    log_dollar_volume: float = 18.0,
    amihud_20: float = 1e-8,
) -> FinraShortVolumeObservation:
    return FinraShortVolumeObservation(
        ticker=ticker,
        as_of_date=as_of,
        short_ratio=short_ratio,
        exempt_share=0.01,
        log_share_volume=log_share_volume,
        log_dollar_volume=log_dollar_volume,
        amihud_20=amihud_20,
        excess_1d=excess_5d / 5,
        excess_5d=excess_5d,
        excess_20d=excess_5d * 2,
        abs_return_1d=abs(excess_5d / 5),
        abs_return_5d=abs(excess_5d),
        abs_return_20d=abs(excess_5d * 2),
    )


def _panel(*, days: int, tickers: int, signal: bool, seed: int = 7) -> list[FinraShortVolumeObservation]:
    rng = np.random.default_rng(seed)
    dates = [item.date() for item in pd.bdate_range("2025-01-02", periods=days)]
    names = [f"T{index:02d}" for index in range(tickers)]
    rows: list[FinraShortVolumeObservation] = []
    for as_of in dates:
        for ticker in names:
            ratio = float(rng.uniform(0.15, 0.65))
            noise = float(rng.normal(0.0, 0.004))
            excess = ((ratio - 0.40) * (1.2 if signal else 0.0)) + noise
            rows.append(
                _observation(
                    ticker,
                    as_of,
                    ratio,
                    excess,
                    log_share_volume=14.5 + float(rng.normal(0.0, 0.2)),
                    log_dollar_volume=17.5 + float(rng.normal(0.0, 0.2)),
                    amihud_20=1e-8 + abs(float(rng.normal(0.0, 1e-9))),
                )
            )
    return rows


def test_walk_forward_detects_pre_registered_short_ratio_signal():
    payload = FinraShortVolumeResearchService(_panel(days=210, tickers=16, signal=True)).build_payload()

    assert payload["mode"] == "shadow"
    assert payload["applied_impact"] == 0
    assert payload["automatic_activation"] is False
    assert payload["activation_ready"] is False
    assert payload["not_short_interest"] is True
    assert payload["provenance"] == "FINRA_OFF_EXCHANGE"
    assert payload["exchange_short_volume_included"] is False
    assert payload["legal_gate"]["commercial_use_allowed"] is False
    assert payload["legal_gate"]["shipping_allowed"] is False
    assert payload["pre_registration"]["primary_feature"] == "short_ratio"
    assert payload["pre_registration"]["primary_target"] == "excess_5d"
    assert payload["verdict"] == "success"
    assert payload["primary"]["significant_folds"] >= 2
    assert payload["short_interest_comparison"]["present"] is False


def test_walk_forward_fails_when_ratio_has_no_incremental_content():
    payload = FinraShortVolumeResearchService(_panel(days=210, tickers=16, signal=False)).build_payload()

    assert payload["sample"]["history_sufficient"] is True
    assert payload["verdict"] == "fail"
    assert payload["primary"]["significant_folds"] < 2


def test_history_depth_gate_is_pre_registered_data_block():
    payload = FinraShortVolumeResearchService(_panel(days=40, tickers=16, signal=True)).build_payload()

    assert payload["verdict"] == "data_blocked"
    assert payload["sample"]["history_sufficient"] is False
    assert payload["sample"]["minimum_trading_days"] == 180


def test_build_observations_uses_price_history_controls_and_forward_excess():
    dates = pd.bdate_range("2026-01-02", periods=40)
    close = np.linspace(100, 140, len(dates))
    stock = pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": np.full(len(dates), 1_000_000.0)},
        index=dates,
    )
    spy = pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close * 0.99, "Volume": np.full(len(dates), 2_000_000.0)},
        index=dates,
    )
    as_of = dates[20].date()
    rows = [
        FinraShortVolumeRow(
            as_of_date=as_of,
            symbol="AAPL",
            short_volume=2_000.0,
            short_exempt_volume=20.0,
            total_volume=8_000.0,
            market="Q",
        )
    ]

    observations = build_observations(rows, {"AAPL": stock}, spy)

    assert len(observations) == 1
    assert observations[0].short_ratio == 0.25
    assert observations[0].excess_5d is not None
    assert observations[0].amihud_20 is not None
    folds = build_walk_forward_folds(_panel(days=210, tickers=12, signal=False))
    assert len(folds) == 3
    assert folds[0].validation_start > folds[0].training_end
