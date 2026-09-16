from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from config.finra_short_interest import (
    BASELINE_FEATURE,
    CONTROLS,
    DAYS_TO_COVER_ELEVATED,
    DAYS_TO_COVER_HIGH,
    EXPERIMENT_ID,
    FROZEN_GATE_FEATURES,
    LEGAL_GATE,
    MIN_CROSS_SECTION,
    MIN_FOLD_OOS_DATES,
    MIN_PUBLICATION_DATES,
    MIN_SHORT_VOLUME_COVERAGE,
    NO_SQUEEZE_POLICY,
    PCT_CHANGE_HIGH,
    PCT_CHANGE_LOW,
    PCT_FLOAT_COVERAGE_FLOOR,
    PCT_FLOAT_REASON,
    PCT_FLOAT_STATUS,
    PRIMARY_TARGET,
    PROVENANCE,
    PUBLICATION_LAG_BUSINESS_DAYS,
    SECONDARY_TARGETS,
    SHORT_VOLUME_ASOF_CALENDAR_DAYS,
    SI_FEATURES,
    SIGNIFICANCE_LEVEL,
    WALK_FORWARD_EMBARGO_DAYS,
    WALK_FORWARD_FOLDS,
)
from domain.scoring.finra_short_interest import (
    LAG_POLICY,
    frozen_delta_high,
    frozen_delta_low,
    frozen_dtc_elevated,
    frozen_dtc_high,
)
from providers.market.finra_short_interest_client import FinraShortInterestRow


TARGETS = (PRIMARY_TARGET, *SECONDARY_TARGETS)
# Newey-West lag in publication-cycle units, not sessions. Cycles are ~10
# sessions apart, so a 20-session target overlaps about two event dates.
NEWEY_WEST_LAGS = {
    "excess_20d": 2,
    "excess_60d": 6,
    "abs_return_20d": 2,
    "abs_return_60d": 6,
}


@dataclass(frozen=True)
class DailyShortVolumePoint:
    """As-of daily short-sale volume ratio used only as the nested baseline.

    This is the KEEP'd CNMS short_ratio family (flow), not short interest.
    Tests inject these points. Live ingest of CNMSshvol lives on the separate
    short-volume branch and is joined here when provided.
    """

    ticker: str
    as_of_date: date
    short_ratio: float


@dataclass(frozen=True)
class FinraShortInterestObservation:
    ticker: str
    settlement_date: date
    publication_date: date
    as_of_date: date
    short_shares: float
    log_short_shares: float
    pct_change_prior: float | None
    days_to_cover: float | None
    delta_high: bool
    delta_low: bool
    dtc_elevated: bool
    dtc_high: bool
    short_ratio: float | None
    log_share_volume: float
    log_dollar_volume: float
    amihud_20: float | None
    excess_20d: float | None
    excess_60d: float | None
    abs_return_20d: float | None
    abs_return_60d: float | None
    pct_float: float | None = None


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    training_end: date
    validation_start: date
    validation_end: date
    training_observations: int
    validation_observations: int
    validation_dates: tuple[date, ...]
    eligible: bool


def _close_series(history: pd.DataFrame) -> pd.Series:
    if history.empty or "Close" not in history.columns:
        return pd.Series(dtype=float)
    close = pd.to_numeric(history["Close"], errors="coerce")
    close.index = pd.to_datetime(history.index).tz_localize(None).normalize()
    return close.dropna().sort_index()


def _volume_series(history: pd.DataFrame) -> pd.Series:
    if history.empty or "Volume" not in history.columns:
        return pd.Series(dtype=float)
    volume = pd.to_numeric(history["Volume"], errors="coerce")
    volume.index = pd.to_datetime(history.index).tz_localize(None).normalize()
    return volume.dropna().sort_index()


def first_session_on_or_after(close: pd.Series, event_date: date) -> date | None:
    if close.empty:
        return None
    stamp = pd.Timestamp(event_date)
    later = close.index[close.index >= stamp]
    if later.empty:
        return None
    return later[0].date()


def _forward_return(close: pd.Series, as_of: date, horizon: int) -> float | None:
    if close.empty:
        return None
    stamp = pd.Timestamp(as_of)
    if stamp not in close.index:
        return None
    location = int(close.index.get_loc(stamp))
    end_location = location + horizon
    if end_location >= len(close):
        return None
    start_price = float(close.iloc[location])
    end_price = float(close.iloc[end_location])
    if start_price <= 0 or not math.isfinite(start_price) or not math.isfinite(end_price):
        return None
    return end_price / start_price - 1.0


def _excess_return(close: pd.Series, spy_close: pd.Series, as_of: date, horizon: int) -> float | None:
    stock_return = _forward_return(close, as_of, horizon)
    benchmark_return = _forward_return(spy_close, as_of, horizon)
    if stock_return is None or benchmark_return is None:
        return None
    return stock_return - benchmark_return


def _abs_return(close: pd.Series, as_of: date, horizon: int) -> float | None:
    value = _forward_return(close, as_of, horizon)
    if value is None:
        return None
    return abs(value)


def _amihud_20(close: pd.Series, volume: pd.Series, as_of: date) -> float | None:
    stamp = pd.Timestamp(as_of)
    aligned = pd.concat({"close": close, "volume": volume}, axis=1).dropna()
    if stamp not in aligned.index:
        return None
    window = aligned.loc[:stamp].tail(20)
    if len(window) < 10:
        return None
    returns = window["close"].pct_change().abs()
    dollar_volume = window["close"] * window["volume"]
    ratio = returns / dollar_volume.replace(0, np.nan)
    values = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return None
    return float(values.median())


def _asof_short_ratio(
    points: Sequence[DailyShortVolumePoint],
    ticker: str,
    as_of: date,
) -> float | None:
    eligible = [
        point
        for point in points
        if point.ticker == ticker
        and point.as_of_date <= as_of
        and (as_of - point.as_of_date).days <= SHORT_VOLUME_ASOF_CALENDAR_DAYS
    ]
    if not eligible:
        return None
    latest = max(eligible, key=lambda item: item.as_of_date)
    return float(latest.short_ratio)


def build_observations(
    rows: Sequence[FinraShortInterestRow],
    price_histories: Mapping[str, pd.DataFrame],
    spy_history: pd.DataFrame,
    short_volume_points: Sequence[DailyShortVolumePoint] = (),
) -> list[FinraShortInterestObservation]:
    spy_close = _close_series(spy_history)
    grouped: dict[str, list[FinraShortInterestRow]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)

    observations: list[FinraShortInterestObservation] = []
    for ticker, ticker_rows in grouped.items():
        history = price_histories.get(ticker)
        if history is None or history.empty:
            continue
        close = _close_series(history)
        volume = _volume_series(history)
        for row in ticker_rows:
            as_of = first_session_on_or_after(close, row.publication_date)
            if as_of is None:
                continue
            stamp = pd.Timestamp(as_of)
            if stamp not in close.index or stamp not in volume.index:
                continue
            share_volume = float(volume.loc[stamp])
            price = float(close.loc[stamp])
            if share_volume < 0 or price <= 0:
                continue
            log_shares = row.log_short_shares
            if log_shares is None:
                continue
            dollar_volume = price * share_volume
            observations.append(
                FinraShortInterestObservation(
                    ticker=ticker,
                    settlement_date=row.settlement_date,
                    publication_date=row.publication_date,
                    as_of_date=as_of,
                    short_shares=float(row.short_shares),
                    log_short_shares=float(log_shares),
                    pct_change_prior=row.pct_change_prior,
                    days_to_cover=row.days_to_cover,
                    delta_high=frozen_delta_high(row.pct_change_prior),
                    delta_low=frozen_delta_low(row.pct_change_prior),
                    dtc_elevated=frozen_dtc_elevated(row.days_to_cover),
                    dtc_high=frozen_dtc_high(row.days_to_cover),
                    short_ratio=_asof_short_ratio(short_volume_points, ticker, as_of),
                    log_share_volume=math.log1p(share_volume),
                    log_dollar_volume=math.log1p(max(dollar_volume, 0.0)),
                    amihud_20=_amihud_20(close, volume, as_of),
                    excess_20d=_excess_return(close, spy_close, as_of, 20),
                    excess_60d=_excess_return(close, spy_close, as_of, 60),
                    abs_return_20d=_abs_return(close, as_of, 20),
                    abs_return_60d=_abs_return(close, as_of, 60),
                    pct_float=None,
                )
            )
    observations.sort(key=lambda item: (item.as_of_date, item.ticker))
    return observations


def _split_dates(dates: Sequence[date], parts: int) -> list[tuple[date, ...]]:
    if parts <= 0 or not dates:
        return []
    size = max(1, math.ceil(len(dates) / parts))
    blocks: list[tuple[date, ...]] = []
    for index in range(0, len(dates), size):
        block = tuple(dates[index : index + size])
        if block:
            blocks.append(block)
        if len(blocks) == parts:
            remainder = tuple(dates[index + size :])
            if remainder:
                blocks[-1] = blocks[-1] + remainder
            break
    return blocks


def build_walk_forward_folds(
    observations: Sequence[FinraShortInterestObservation],
) -> list[WalkForwardFold]:
    unique_dates = sorted({row.as_of_date for row in observations})
    if len(unique_dates) < 8:
        return []
    initial_training_dates = max(4, math.ceil(len(unique_dates) * 0.40))
    validation_pool = unique_dates[initial_training_dates:]
    blocks = _split_dates(validation_pool, min(WALK_FORWARD_FOLDS, len(validation_pool)))
    folds: list[WalkForwardFold] = []
    for index, validation_dates in enumerate(blocks, start=1):
        validation_start = validation_dates[0]
        training_end = validation_start - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)
        training_rows = [row for row in observations if row.as_of_date <= training_end]
        validation_rows = [row for row in observations if row.as_of_date in set(validation_dates)]
        eligible = (
            len({row.as_of_date for row in training_rows}) >= 4
            and len({row.as_of_date for row in validation_rows}) >= MIN_FOLD_OOS_DATES
            and len(validation_rows) >= MIN_CROSS_SECTION * MIN_FOLD_OOS_DATES // 2
        )
        folds.append(
            WalkForwardFold(
                fold=index,
                training_end=training_end,
                validation_start=validation_start,
                validation_end=validation_dates[-1],
                training_observations=len(training_rows),
                validation_observations=len(validation_rows),
                validation_dates=tuple(validation_dates),
                eligible=eligible,
            )
        )
    return folds


def _normal_sf(z: float) -> float:
    return 0.5 * (1.0 - math.erf(abs(z) / math.sqrt(2.0)))


def _spearman(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < MIN_CROSS_SECTION:
        return None
    x_rank = pd.Series(x).rank(method="average").to_numpy()
    y_rank = pd.Series(y).rank(method="average").to_numpy()
    if np.std(x_rank) == 0 or np.std(y_rank) == 0:
        return None
    corr = float(np.corrcoef(x_rank, y_rank)[0, 1])
    if not math.isfinite(corr):
        return None
    return corr


def _ols_beta(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    return beta


def _apply_beta(x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    return design @ beta


def _feature_value(row: FinraShortInterestObservation, feature_name: str) -> float | None:
    raw = getattr(row, feature_name)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    value = float(raw)
    if not math.isfinite(value):
        return None
    return value


def _control_matrix(
    rows: Sequence[FinraShortInterestObservation],
    control_names: Sequence[str],
) -> tuple[list[FinraShortInterestObservation], np.ndarray]:
    usable: list[FinraShortInterestObservation] = []
    vectors: list[list[float]] = []
    for row in rows:
        if row.amihud_20 is None:
            continue
        vector: list[float] = []
        skip = False
        for name in control_names:
            value = _feature_value(row, name)
            if value is None:
                skip = True
                break
            vector.append(value)
        if skip:
            continue
        usable.append(row)
        vectors.append(vector)
    if not vectors:
        return [], np.empty((0, len(control_names)))
    return usable, np.array(vectors, dtype=float)


def _residualize_cross_section(
    rows: Sequence[FinraShortInterestObservation],
    *,
    feature_name: str,
    control_names: Sequence[str],
) -> dict[tuple[str, date], float]:
    """Residualize a feature on contemporaneous controls within each event date.

    Controls are known on the publication session. Using the same-date
    cross-section avoids leaking later coefficients and is the nested test
    for incremental SI content versus daily short_ratio.
    """

    by_date: dict[date, list[FinraShortInterestObservation]] = {}
    for row in rows:
        by_date.setdefault(row.as_of_date, []).append(row)
    residuals: dict[tuple[str, date], float] = {}
    min_rows = max(MIN_CROSS_SECTION, len(control_names) + 2)
    for group in by_date.values():
        usable, matrix = _control_matrix(group, control_names)
        y_values: list[float] = []
        x_values: list[np.ndarray] = []
        kept: list[FinraShortInterestObservation] = []
        for row, x_row in zip(usable, matrix, strict=True):
            feature = _feature_value(row, feature_name)
            if feature is None:
                continue
            kept.append(row)
            y_values.append(feature)
            x_values.append(x_row)
        if len(y_values) < min_rows:
            continue
        y = np.array(y_values, dtype=float)
        x = np.vstack(x_values)
        beta = _ols_beta(y, x)
        predicted = _apply_beta(x, beta)
        for row, hat in zip(kept, predicted, strict=True):
            feature = _feature_value(row, feature_name)
            if feature is None:
                continue
            residuals[(row.ticker, row.as_of_date)] = float(feature) - float(hat)
    return residuals


def _residualize_mapped_values(
    rows: Sequence[FinraShortInterestObservation],
    values: Mapping[tuple[str, date], float],
    controls: Mapping[tuple[str, date], float],
) -> dict[tuple[str, date], float]:
    by_date: dict[date, list[FinraShortInterestObservation]] = {}
    for row in rows:
        by_date.setdefault(row.as_of_date, []).append(row)
    residuals: dict[tuple[str, date], float] = {}
    for group in by_date.values():
        ys: list[float] = []
        xs: list[float] = []
        kept: list[FinraShortInterestObservation] = []
        for row in group:
            key = (row.ticker, row.as_of_date)
            if key not in values or key not in controls:
                continue
            kept.append(row)
            ys.append(float(values[key]))
            xs.append(float(controls[key]))
        if len(ys) < MIN_CROSS_SECTION:
            continue
        y = np.array(ys, dtype=float)
        x = np.array(xs, dtype=float).reshape(-1, 1)
        if float(np.std(x)) == 0:
            continue
        beta = _ols_beta(y, x)
        predicted = _apply_beta(x, beta)
        for row, hat in zip(kept, predicted, strict=True):
            key = (row.ticker, row.as_of_date)
            residuals[key] = float(values[key]) - float(hat)
    return residuals


def _nested_residuals(
    rows: Sequence[FinraShortInterestObservation],
    *,
    feature_name: str,
) -> dict[tuple[str, date], float]:
    """Incremental SI residual after liquidity, then after daily short_ratio.

    Two-step Frisch-Waugh on the publication-date cross-section: first strip
    liquidity, then strip the KEEP'd short-volume ratio. Avoids a single
    overparameterized CS OLS of SI on short_ratio plus three liquidity terms.
    """

    feature_liq = _residualize_cross_section(
        rows,
        feature_name=feature_name,
        control_names=CONTROLS,
    )
    short_volume_liq = _residualize_cross_section(
        rows,
        feature_name=BASELINE_FEATURE,
        control_names=CONTROLS,
    )
    return _residualize_mapped_values(rows, feature_liq, short_volume_liq)


def _date_ics(
    rows: Sequence[FinraShortInterestObservation],
    residuals: Mapping[tuple[str, date], float],
    target_name: str,
) -> list[float]:
    by_date: dict[date, list[tuple[float, float]]] = {}
    for row in rows:
        residual = residuals.get((row.ticker, row.as_of_date))
        target = getattr(row, target_name)
        if residual is None or target is None:
            continue
        by_date.setdefault(row.as_of_date, []).append((residual, float(target)))
    ics: list[float] = []
    for pairs in by_date.values():
        if len(pairs) < MIN_CROSS_SECTION:
            continue
        x = np.array([pair[0] for pair in pairs], dtype=float)
        y = np.array([pair[1] for pair in pairs], dtype=float)
        # Collinear nested residuals (SI fully explained by short_ratio +
        # liquidity) have no incremental variation to score.
        if float(np.std(x, ddof=0)) < 1e-10:
            continue
        ic = _spearman(x, y)
        if ic is not None:
            ics.append(ic)
    return ics


def _newey_west_mean(values: Sequence[float], lag: int) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    array = np.array(values, dtype=float)
    n = len(array)
    mu = float(array.mean())
    if n < 3:
        return mu, None, None
    errors = array - mu
    gamma0 = float(np.dot(errors, errors) / n)
    variance = gamma0
    max_lag = min(max(lag, 0), n - 1)
    for k in range(1, max_lag + 1):
        weight = 1.0 - k / (max_lag + 1)
        gamma = float(np.dot(errors[k:], errors[:-k]) / n)
        variance += 2.0 * weight * gamma
    se = math.sqrt(max(variance, 0.0) / n)
    if se <= 0:
        return mu, None, None
    t_stat = mu / se
    p_value = 2.0 * _normal_sf(t_stat)
    return mu, t_stat, p_value


def _evaluate_feature(
    observations: Sequence[FinraShortInterestObservation],
    folds: Sequence[WalkForwardFold],
    *,
    feature_name: str,
    target_name: str,
    control_names: Sequence[str],
) -> dict[str, Any]:
    fold_rows: list[dict[str, Any]] = []
    significant_folds = 0
    eligible_folds = 0
    for fold in folds:
        validation = [row for row in observations if row.as_of_date in set(fold.validation_dates)]
        if feature_name in SI_FEATURES or feature_name in FROZEN_GATE_FEATURES:
            residuals = _nested_residuals(validation, feature_name=feature_name)
        else:
            residuals = _residualize_cross_section(
                validation,
                feature_name=feature_name,
                control_names=control_names,
            )
        ics = _date_ics(validation, residuals, target_name)
        mean_ic, t_stat, p_value = _newey_west_mean(ics, NEWEY_WEST_LAGS[target_name])
        eligible = fold.eligible and len(ics) >= MIN_FOLD_OOS_DATES
        significant = eligible and p_value is not None and p_value < SIGNIFICANCE_LEVEL
        if eligible:
            eligible_folds += 1
        if significant:
            significant_folds += 1
        fold_rows.append(
            {
                "fold": fold.fold,
                "training_end": fold.training_end.isoformat(),
                "validation_start": fold.validation_start.isoformat(),
                "validation_end": fold.validation_end.isoformat(),
                "eligible": eligible,
                "cross_section_ics": len(ics),
                "mean_ic": round(mean_ic, 4) if mean_ic is not None else None,
                "t_stat": round(t_stat, 3) if t_stat is not None else None,
                "p_value": round(p_value, 4) if p_value is not None else None,
                "significant": significant,
            }
        )
    return {
        "feature": feature_name,
        "target": target_name,
        "controls": list(control_names),
        "eligible_folds": eligible_folds,
        "significant_folds": significant_folds,
        "success_threshold": "significant incremental association in >=2/3 eligible folds",
        "folds": fold_rows,
    }


def _short_volume_coverage(observations: Sequence[FinraShortInterestObservation]) -> float:
    if not observations:
        return 0.0
    covered = sum(1 for row in observations if row.short_ratio is not None)
    return covered / len(observations)


def _pre_registration() -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": (
            "Biweekly FINRA short-interest levels (shares short, Δ vs prior settlement, "
            "days-to-cover) contain calibratable shadow information distinct from daily "
            "FINRA short-sale volume ratio after liquidity controls."
        ),
        "falsifier": (
            "After lag-correct dating to publication date, SI level/Δ/DTC features show "
            "no walk-forward association with pre-registered targets once daily "
            "short-volume ratio and liquidity controls are included; OR %float cannot "
            "be built at usable coverage."
        ),
        "event_date": "publication_date",
        "publication_lag_weekdays": PUBLICATION_LAG_BUSINESS_DAYS,
        "lag_policy": LAG_POLICY,
        "features": list(SI_FEATURES),
        "frozen_gates": {
            "pct_change_high": PCT_CHANGE_HIGH,
            "pct_change_low": PCT_CHANGE_LOW,
            "days_to_cover_elevated": DAYS_TO_COVER_ELEVATED,
            "days_to_cover_high": DAYS_TO_COVER_HIGH,
            "features": list(FROZEN_GATE_FEATURES),
            "shopping_allowed": False,
        },
        "pct_float": {
            "status": PCT_FLOAT_STATUS,
            "coverage_floor": PCT_FLOAT_COVERAGE_FLOOR,
            "reason": PCT_FLOAT_REASON,
        },
        "baseline_feature": BASELINE_FEATURE,
        "baseline_definition": "Daily FINRA shortVolume/totalVolume ratio, as-of joined to SI publication date.",
        "primary_target": PRIMARY_TARGET,
        "targets": list(TARGETS),
        "controls": list(CONTROLS),
        "nested_controls": [BASELINE_FEATURE, *CONTROLS],
        "association_metric": (
            "Mean publication-date cross-sectional Spearman IC of the SI feature "
            "after two-step Frisch-Waugh residualization: liquidity controls first, "
            "then daily short_ratio. Newey-West lag is in publication-cycle units "
            "(2 for 20-session targets, 6 for 60-session targets)."
        ),
        "walk_forward": {
            "requested_folds": WALK_FORWARD_FOLDS,
            "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
            "design": "expanding_window_with_calendar_embargo",
            "split_basis": "publication_asof_session",
        },
        "data_gate": {
            "minimum_publication_dates": MIN_PUBLICATION_DATES,
            "minimum_oos_dates_per_fold": MIN_FOLD_OOS_DATES,
            "minimum_cross_section": MIN_CROSS_SECTION,
            "minimum_short_volume_coverage": MIN_SHORT_VOLUME_COVERAGE,
        },
        "success_rule": (
            "At least one SI feature (log_short_shares, pct_change_prior, days_to_cover) "
            "adds significant incremental lift vs short-volume-only in at least 2 of 3 "
            "eligible folds on excess_20d. %float either ships with coverage at or above "
            "the pre-registered floor or is explicitly deferred."
        ),
        "overfitting_mitigations": [
            "Publication dating only; settlement dates are never event dates.",
            "Δ and DTC gate thresholds frozen before evaluation.",
            "No squeeze narrative products or labels.",
            "%float deferred; no ad-hoc float denominator.",
            "Nested residualization vs daily short_ratio plus liquidity controls.",
        ],
        "no_squeeze_policy": NO_SQUEEZE_POLICY,
        "provenance": PROVENANCE,
    }


def _verdict(
    *,
    publication_dates: int,
    short_volume_coverage: float,
    nested_results: Sequence[Mapping[str, Any]],
) -> tuple[str, str]:
    if publication_dates < MIN_PUBLICATION_DATES:
        return (
            "data_blocked",
            "FINRA short-interest publication history is too short for the pre-registered 3-fold walk-forward.",
        )
    if short_volume_coverage < MIN_SHORT_VOLUME_COVERAGE:
        return (
            "data_blocked",
            "Daily short-volume coverage is below the nested-comparison floor, so incremental SI lift cannot be scored.",
        )
    lifting = [
        row
        for row in nested_results
        if int(row.get("eligible_folds") or 0) >= WALK_FORWARD_FOLDS
        and int(row.get("significant_folds") or 0) >= 2
    ]
    if lifting:
        names = ", ".join(str(row["feature"]) for row in lifting)
        return (
            "success",
            f"{names} added significant incremental lift versus short-volume-only in at least two walk-forward folds.",
        )
    return (
        "fail",
        "SI level/Δ/DTC features were fully redundant with daily short-volume plus liquidity controls on the primary target.",
    )


class FinraShortInterestResearchService:
    """Pre-registered nested walk-forward for FINRA biweekly short interest."""

    def __init__(
        self,
        observations: Sequence[FinraShortInterestObservation] | None = None,
    ) -> None:
        self._observations = tuple(observations) if observations is not None else ()

    def build_payload(self) -> dict[str, Any]:
        observations = list(self._observations)
        publication_dates = len({row.as_of_date for row in observations})
        tickers = sorted({row.ticker for row in observations})
        short_volume_coverage = _short_volume_coverage(observations)
        nested_panel = [row for row in observations if row.short_ratio is not None]
        folds = build_walk_forward_folds(nested_panel if nested_panel else observations)
        nested_controls = (BASELINE_FEATURE, *CONTROLS)
        nested_primary = [
            _evaluate_feature(
                nested_panel,
                folds,
                feature_name=feature,
                target_name=PRIMARY_TARGET,
                control_names=nested_controls,
            )
            for feature in SI_FEATURES
        ]
        nested_secondary = [
            _evaluate_feature(
                nested_panel,
                folds,
                feature_name=feature,
                target_name=target,
                control_names=nested_controls,
            )
            for feature in SI_FEATURES
            for target in SECONDARY_TARGETS
        ]
        frozen_gates = [
            _evaluate_feature(
                nested_panel,
                folds,
                feature_name=feature,
                target_name=PRIMARY_TARGET,
                control_names=nested_controls,
            )
            for feature in FROZEN_GATE_FEATURES
        ]
        baseline = _evaluate_feature(
            nested_panel,
            folds,
            feature_name=BASELINE_FEATURE,
            target_name=PRIMARY_TARGET,
            control_names=CONTROLS,
        )
        verdict, verdict_summary = _verdict(
            publication_dates=publication_dates,
            short_volume_coverage=short_volume_coverage,
            nested_results=nested_primary,
        )
        lifting_features = [
            row["feature"]
            for row in nested_primary
            if int(row.get("significant_folds") or 0) >= 2
            and int(row.get("eligible_folds") or 0) >= WALK_FORWARD_FOLDS
        ]
        return {
            "status": "research_only",
            "mode": "shadow",
            "automatic_activation": False,
            "activation_ready": False,
            "applied_impact": 0,
            "cannot_flip_live": True,
            "experiment_id": EXPERIMENT_ID,
            "verdict": verdict,
            "verdict_summary": verdict_summary,
            "feature_family": "short_interest",
            "not_short_volume": True,
            "squeeze_narrative": False,
            "provenance": PROVENANCE,
            "legal_gate": dict(LEGAL_GATE),
            "pre_registration": _pre_registration(),
            "pct_float": {
                "status": PCT_FLOAT_STATUS,
                "coverage": 0.0,
                "coverage_floor": PCT_FLOAT_COVERAGE_FLOOR,
                "shipped": False,
                "reason": PCT_FLOAT_REASON,
            },
            "sample": {
                "observations": len(observations),
                "nested_observations": len(nested_panel),
                "tickers": len(tickers),
                "publication_dates": publication_dates,
                "minimum_publication_dates": MIN_PUBLICATION_DATES,
                "history_sufficient": publication_dates >= MIN_PUBLICATION_DATES,
                "short_volume_coverage": round(short_volume_coverage, 4),
                "short_volume_coverage_floor": MIN_SHORT_VOLUME_COVERAGE,
                "short_volume_coverage_sufficient": short_volume_coverage >= MIN_SHORT_VOLUME_COVERAGE,
            },
            "walk_forward_folds": [
                {
                    "fold": fold.fold,
                    "training_end": fold.training_end.isoformat(),
                    "validation_start": fold.validation_start.isoformat(),
                    "validation_end": fold.validation_end.isoformat(),
                    "training_observations": fold.training_observations,
                    "validation_observations": fold.validation_observations,
                    "validation_dates": len(fold.validation_dates),
                    "eligible": fold.eligible,
                }
                for fold in folds
            ],
            "baseline_short_volume": baseline,
            "nested_primary": nested_primary,
            "lifting_features": lifting_features,
            "nested_secondary": nested_secondary,
            "frozen_gate_screens": frozen_gates,
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_recommendation_changes": False,
                "commercial_shipping": False,
                "squeeze_narrative_products": False,
                "message": (
                    "Shadow-only. This analysis never writes live scores, recommendations, "
                    "or squeeze-narrative products."
                ),
            },
        }


def empty_research_payload(*, reason: str) -> dict[str, Any]:
    payload = FinraShortInterestResearchService(observations=()).build_payload()
    payload["verdict"] = "data_blocked"
    payload["verdict_summary"] = reason
    payload["sample"]["history_sufficient"] = False
    return payload


__all__ = [
    "EXPERIMENT_ID",
    "DailyShortVolumePoint",
    "FinraShortInterestObservation",
    "FinraShortInterestResearchService",
    "WalkForwardFold",
    "build_observations",
    "build_walk_forward_folds",
    "empty_research_payload",
    "first_session_on_or_after",
]
