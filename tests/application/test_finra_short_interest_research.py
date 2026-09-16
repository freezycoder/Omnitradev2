from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from application.finra_short_interest_research_service import (
    DailyShortVolumePoint,
    FinraShortInterestObservation,
    FinraShortInterestResearchService,
    build_observations,
    build_walk_forward_folds,
)
from config.finra_short_interest import MIN_PUBLICATION_DATES, PRIMARY_TARGET
from providers.market.finra_short_interest_client import FinraShortInterestRow, publication_date_from_settlement


def _observation(
    ticker: str,
    as_of: date,
    *,
    short_shares: float,
    pct_change_prior: float,
    days_to_cover: float,
    short_ratio: float,
    excess_20d: float,
    log_share_volume: float = 15.0,
    log_dollar_volume: float = 18.0,
    amihud_20: float = 1e-8,
    log_short_shares: float | None = None,
) -> FinraShortInterestObservation:
    settlement = as_of
    publication = publication_date_from_settlement(settlement)
    return FinraShortInterestObservation(
        ticker=ticker,
        settlement_date=settlement,
        publication_date=publication,
        as_of_date=as_of,
        short_shares=short_shares,
        log_short_shares=float(np.log1p(short_shares) if log_short_shares is None else log_short_shares),
        pct_change_prior=pct_change_prior,
        days_to_cover=days_to_cover,
        delta_high=pct_change_prior >= 20,
        delta_low=pct_change_prior <= -20,
        dtc_elevated=days_to_cover >= 5,
        dtc_high=days_to_cover >= 10,
        short_ratio=short_ratio,
        log_share_volume=log_share_volume,
        log_dollar_volume=log_dollar_volume,
        amihud_20=amihud_20,
        excess_20d=excess_20d,
        excess_60d=excess_20d * 1.4,
        abs_return_20d=abs(excess_20d),
        abs_return_60d=abs(excess_20d) * 1.4,
        pct_float=None,
    )


def _panel(*, dates: int, tickers: int, mode: str, seed: int = 11) -> list[FinraShortInterestObservation]:
    rng = np.random.default_rng(seed)
    as_ofs = [item.date() for item in pd.bdate_range("2023-01-03", periods=dates, freq="10B")]
    names = [f"T{index:02d}" for index in range(tickers)]
    rows: list[FinraShortInterestObservation] = []
    for as_of in as_ofs:
        for ticker in names:
            short_ratio = float(rng.uniform(0.18, 0.52))
            if mode == "incremental":
                days_to_cover = float(rng.uniform(1.0, 9.0))
                pct_change = float(rng.normal(0.0, 8.0))
                short_shares = float(rng.uniform(1_000_000, 8_000_000))
                noise = float(rng.normal(0.0, 0.004))
                excess = (days_to_cover - 5.0) * 0.012 + noise
            else:
                # Exact copy of the nested baseline: no leftover SI variation
                # after Frisch-Waugh, so the walk-forward must FAIL.
                noise = float(rng.normal(0.0, 0.004))
                days_to_cover = short_ratio
                pct_change = short_ratio
                short_shares = float(np.expm1(max(short_ratio, 0.0)))
                excess = (short_ratio - 0.35) * 0.05 + noise
            kwargs = {}
            if mode != "incremental":
                kwargs["log_short_shares"] = short_ratio
            rows.append(
                _observation(
                    ticker,
                    as_of,
                    short_shares=short_shares,
                    pct_change_prior=pct_change,
                    days_to_cover=days_to_cover,
                    short_ratio=short_ratio,
                    excess_20d=excess,
                    log_share_volume=14.5 + float(rng.normal(0.0, 0.15)),
                    log_dollar_volume=17.5 + float(rng.normal(0.0, 0.15)),
                    amihud_20=1e-8 + abs(float(rng.normal(0.0, 1e-9))),
                    **kwargs,
                )
            )
    return rows


def test_walk_forward_detects_incremental_si_lift_versus_short_volume():
    payload = FinraShortInterestResearchService(
        _panel(dates=48, tickers=16, mode="incremental")
    ).build_payload()

    assert payload["mode"] == "shadow"
    assert payload["applied_impact"] == 0
    assert payload["automatic_activation"] is False
    assert payload["cannot_flip_live"] is True
    assert payload["squeeze_narrative"] is False
    assert payload["pct_float"]["status"] == "deferred"
    assert payload["pct_float"]["shipped"] is False
    assert payload["pre_registration"]["event_date"] == "publication_date"
    assert payload["pre_registration"]["primary_target"] == PRIMARY_TARGET
    assert payload["pre_registration"]["frozen_gates"]["shopping_allowed"] is False
    assert payload["verdict"] == "success"
    assert "days_to_cover" in payload["lifting_features"]
    dtc = next(row for row in payload["nested_primary"] if row["feature"] == "days_to_cover")
    assert dtc["significant_folds"] >= 2


def test_walk_forward_fails_when_si_is_redundant_with_short_volume():
    payload = FinraShortInterestResearchService(
        _panel(dates=48, tickers=16, mode="redundant")
    ).build_payload()

    assert payload["sample"]["history_sufficient"] is True
    assert payload["sample"]["short_volume_coverage_sufficient"] is True
    assert payload["verdict"] == "fail"
    assert payload["lifting_features"] == []


def test_missing_short_volume_coverage_is_data_blocked():
    rows = _panel(dates=48, tickers=16, mode="incremental")
    rows = [
        FinraShortInterestObservation(
            **{**item.__dict__, "short_ratio": None if index % 3 else item.short_ratio}
        )
        for index, item in enumerate(rows)
    ]
    payload = FinraShortInterestResearchService(rows).build_payload()

    assert payload["verdict"] == "data_blocked"
    assert payload["sample"]["short_volume_coverage_sufficient"] is False


def test_history_depth_gate_is_pre_registered_data_block():
    payload = FinraShortInterestResearchService(
        _panel(dates=12, tickers=16, mode="incremental")
    ).build_payload()

    assert payload["verdict"] == "data_blocked"
    assert payload["sample"]["history_sufficient"] is False
    assert payload["sample"]["minimum_publication_dates"] == MIN_PUBLICATION_DATES


def test_build_observations_dates_to_publication_not_settlement():
    dates = pd.bdate_range("2026-07-31", periods=90)
    close = np.linspace(100, 140, len(dates))
    stock = pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": np.full(len(dates), 1_000_000.0)},
        index=dates,
    )
    spy = pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close * 0.99, "Volume": np.full(len(dates), 2_000_000.0)},
        index=dates,
    )
    settlement = date(2026, 7, 31)
    publication = publication_date_from_settlement(settlement)
    rows = [
        FinraShortInterestRow(
            symbol="AAPL",
            settlement_date=settlement,
            publication_date=publication,
            short_shares=1_000_000,
            previous_short_shares=800_000,
            pct_change_prior=25.0,
            days_to_cover=6.0,
            average_daily_volume=500_000,
        )
    ]
    points = [DailyShortVolumePoint(ticker="AAPL", as_of_date=publication, short_ratio=0.33)]

    observations = build_observations(rows, {"AAPL": stock}, spy, points)

    assert len(observations) == 1
    assert observations[0].publication_date == publication
    assert observations[0].as_of_date >= publication
    assert observations[0].as_of_date != settlement
    assert observations[0].short_ratio == 0.33
    assert observations[0].pct_float is None
    folds = build_walk_forward_folds(_panel(dates=48, tickers=12, mode="redundant"))
    assert len(folds) == 3
    assert folds[0].validation_start > folds[0].training_end
