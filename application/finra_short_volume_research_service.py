from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from domain.scoring.finra_short_volume import LEGAL_GATE, PERMANENT_COVERAGE_CAVEAT
from providers.market.finra_short_volume_client import FinraShortVolumeRow


EXPERIMENT_ID = "finra_cnms_short_volume_shadow_v1"
WALK_FORWARD_FOLDS = 3
WALK_FORWARD_EMBARGO_DAYS = 5
MIN_TRADING_DAYS = 180
MIN_FOLD_OOS_DATES = 20
MIN_CROSS_SECTION = 8
SIGNIFICANCE_LEVEL = 0.05
PRIMARY_FEATURE = "short_ratio"
PRIMARY_TARGET = "excess_5d"
SECONDARY_FEATURE = "exempt_share"
FEATURE_DEFINITION = "ShortVolume / TotalVolume from FINRA CNMSshvol; TotalVolume<=0 is missing."
CONTROLS = ("log_share_volume", "log_dollar_volume", "amihud_20")
TARGETS = ("excess_1d", "excess_5d", "excess_20d", "abs_return_1d", "abs_return_5d", "abs_return_20d")
HORIZON_DAYS = {
    "excess_1d": 1,
    "excess_5d": 5,
    "excess_20d": 20,
    "abs_return_1d": 1,
    "abs_return_5d": 5,
    "abs_return_20d": 20,
}
SHORT_INTEREST_COMPARISON_POLICY = (
    "Compare only if an existing short-interest feature is present; do not invent one."
)


@dataclass(frozen=True)
class FinraShortVolumeObservation:
    ticker: str
    as_of_date: date
    short_ratio: float
    exempt_share: float | None
    log_share_volume: float
    log_dollar_volume: float
    amihud_20: float | None
    excess_1d: float | None
    excess_5d: float | None
    excess_20d: float | None
    abs_return_1d: float | None
    abs_return_5d: float | None
    abs_return_20d: float | None


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


def _amihud_20(close: pd.Series, volume: pd.Series, as_of: date) -> float | None:
    stamp = pd.Timestamp(as_of)
    if stamp not in close.index:
        return None
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


def build_observations(
    rows: Sequence[FinraShortVolumeRow],
    price_histories: Mapping[str, pd.DataFrame],
    spy_history: pd.DataFrame,
) -> list[FinraShortVolumeObservation]:
    spy_close = _close_series(spy_history)
    grouped: dict[str, list[FinraShortVolumeRow]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)

    observations: list[FinraShortVolumeObservation] = []
    for ticker, ticker_rows in grouped.items():
        history = price_histories.get(ticker)
        if history is None or history.empty:
            continue
        close = _close_series(history)
        volume = _volume_series(history)
        for row in ticker_rows:
            short_ratio = row.short_ratio
            if short_ratio is None:
                continue
            stamp = pd.Timestamp(row.as_of_date)
            if stamp not in close.index or stamp not in volume.index:
                continue
            share_volume = float(volume.loc[stamp])
            price = float(close.loc[stamp])
            if share_volume < 0 or price <= 0:
                continue
            dollar_volume = price * share_volume
            excess_1d = _excess_return(close, spy_close, row.as_of_date, 1)
            excess_5d = _excess_return(close, spy_close, row.as_of_date, 5)
            excess_20d = _excess_return(close, spy_close, row.as_of_date, 20)
            observations.append(
                FinraShortVolumeObservation(
                    ticker=ticker,
                    as_of_date=row.as_of_date,
                    short_ratio=float(short_ratio),
                    exempt_share=row.exempt_share,
                    log_share_volume=math.log1p(share_volume),
                    log_dollar_volume=math.log1p(max(dollar_volume, 0.0)),
                    amihud_20=_amihud_20(close, volume, row.as_of_date),
                    excess_1d=excess_1d,
                    excess_5d=excess_5d,
                    excess_20d=excess_20d,
                    abs_return_1d=_abs_return(close, row.as_of_date, 1),
                    abs_return_5d=_abs_return(close, row.as_of_date, 5),
                    abs_return_20d=_abs_return(close, row.as_of_date, 20),
                )
            )
    observations.sort(key=lambda item: (item.as_of_date, item.ticker))
    return observations


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


def build_walk_forward_folds(observations: Sequence[FinraShortVolumeObservation]) -> list[WalkForwardFold]:
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
            and len(validation_rows) >= MIN_CROSS_SECTION * MIN_FOLD_OOS_DATES // 4
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


def _residualize_feature(
    training: Sequence[FinraShortVolumeObservation],
    validation: Sequence[FinraShortVolumeObservation],
    *,
    feature_name: str,
) -> dict[tuple[str, date], float]:
    train_rows = [
        row
        for row in training
        if getattr(row, feature_name) is not None and row.amihud_20 is not None
    ]
    if len(train_rows) < MIN_CROSS_SECTION:
        return {}
    y = np.array([float(getattr(row, feature_name)) for row in train_rows], dtype=float)
    x = np.array(
        [
            [row.log_share_volume, row.log_dollar_volume, float(row.amihud_20)]
            for row in train_rows
        ],
        dtype=float,
    )
    beta = _ols_beta(y, x)
    residuals: dict[tuple[str, date], float] = {}
    for row in validation:
        if getattr(row, feature_name) is None or row.amihud_20 is None:
            continue
        predicted = _apply_beta(
            np.array([[row.log_share_volume, row.log_dollar_volume, float(row.amihud_20)]], dtype=float),
            beta,
        )[0]
        residuals[(row.ticker, row.as_of_date)] = float(getattr(row, feature_name)) - float(predicted)
    return residuals


def _daily_ics(
    rows: Sequence[FinraShortVolumeObservation],
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
    observations: Sequence[FinraShortVolumeObservation],
    folds: Sequence[WalkForwardFold],
    *,
    feature_name: str,
    target_name: str,
) -> dict[str, Any]:
    fold_rows: list[dict[str, Any]] = []
    significant_folds = 0
    eligible_folds = 0
    for fold in folds:
        training = [row for row in observations if row.as_of_date <= fold.training_end]
        validation = [row for row in observations if row.as_of_date in set(fold.validation_dates)]
        residuals = _residualize_feature(training, validation, feature_name=feature_name)
        ics = _daily_ics(validation, residuals, target_name)
        mean_ic, t_stat, p_value = _newey_west_mean(ics, HORIZON_DAYS[target_name])
        eligible = fold.eligible and len(ics) >= MIN_FOLD_OOS_DATES
        significant = (
            eligible
            and p_value is not None
            and p_value < SIGNIFICANCE_LEVEL
        )
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
                "daily_ic_count": len(ics),
                "mean_daily_ic": round(mean_ic, 4) if mean_ic is not None else None,
                "t_stat": round(t_stat, 3) if t_stat is not None else None,
                "p_value": round(p_value, 4) if p_value is not None else None,
                "significant": significant,
            }
        )
    return {
        "feature": feature_name,
        "target": target_name,
        "eligible_folds": eligible_folds,
        "significant_folds": significant_folds,
        "success_threshold": "significant association in >=2/3 eligible folds",
        "folds": fold_rows,
    }


def _pre_registration(*, short_interest_feature_present: bool) -> dict[str, Any]:
    return {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis": (
            "Daily FINRA CNMS short_ratio (and exempt_share) is a calibratable shadow "
            "microstructure factor distinct from bi-monthly short interest, with measurable "
            "association to forward excess returns or absolute-return volatility after "
            "volume/liquidity controls."
        ),
        "falsifier": (
            "Ratio (and exempt share) has no walk-forward predictive content for pre-registered "
            "targets after volume/liquidity controls, or effects vanish once exchange short "
            "volume is acknowledged missing, or history depth is insufficient."
        ),
        "primary_feature": PRIMARY_FEATURE,
        "primary_feature_definition": FEATURE_DEFINITION,
        "secondary_feature": SECONDARY_FEATURE,
        "primary_target": PRIMARY_TARGET,
        "targets": list(TARGETS),
        "controls": list(CONTROLS),
        "control_source": "price-history volume, dollar volume, and 20-session Amihud; not FINRA TotalVolume",
        "association_metric": (
            "Mean daily cross-sectional Spearman IC of residualized feature versus target, "
            "with Newey-West t-stat lag equal to the return horizon."
        ),
        "walk_forward": {
            "requested_folds": WALK_FORWARD_FOLDS,
            "embargo_days": WALK_FORWARD_EMBARGO_DAYS,
            "design": "expanding_window_with_calendar_embargo",
            "split_basis": "finra_file_date",
        },
        "data_gate": {
            "minimum_trading_days": MIN_TRADING_DAYS,
            "minimum_oos_dates_per_fold": MIN_FOLD_OOS_DATES,
            "minimum_cross_section": MIN_CROSS_SECTION,
        },
        "success_rule": "Primary target significant in at least 2 of 3 eligible folds.",
        "overfitting_mitigations": [
            "One primary ratio definition; no post-hoc percentile thresholds.",
            "Targets and controls pre-registered.",
            "Exempt share is reported separately and is not combined with short interest.",
            "Facility-coverage caveat is permanent.",
        ],
        "short_interest_comparison": SHORT_INTEREST_COMPARISON_POLICY,
        "short_interest_feature_present": short_interest_feature_present,
        "provenance": "FINRA_OFF_EXCHANGE",
        "exchange_short_volume_included": False,
        "coverage_caveat": PERMANENT_COVERAGE_CAVEAT,
    }


def _verdict(
    *,
    trading_days: int,
    primary: Mapping[str, Any],
) -> tuple[str, str]:
    if trading_days < MIN_TRADING_DAYS or int(primary.get("eligible_folds") or 0) < WALK_FORWARD_FOLDS:
        return (
            "data_blocked",
            "FINRA CNMS history is too short for the pre-registered 3-fold walk-forward design.",
        )
    significant = int(primary.get("significant_folds") or 0)
    eligible = int(primary.get("eligible_folds") or 0)
    if eligible >= WALK_FORWARD_FOLDS and significant >= 2:
        return (
            "success",
            "Primary 5d excess-return IC was significant in at least two walk-forward folds after liquidity controls.",
        )
    return (
        "fail",
        "No significant walk-forward association for the primary target after volume/liquidity controls.",
    )


class FinraShortVolumeResearchService:
    """Pre-registered shadow walk-forward for FINRA CNMS short volume."""

    def __init__(
        self,
        observations: Sequence[FinraShortVolumeObservation] | None = None,
        *,
        short_interest_feature_present: bool = False,
    ) -> None:
        self._observations = tuple(observations) if observations is not None else ()
        self._short_interest_feature_present = short_interest_feature_present

    def build_payload(self) -> dict[str, Any]:
        observations = list(self._observations)
        trading_days = len({row.as_of_date for row in observations})
        tickers = sorted({row.ticker for row in observations})
        folds = build_walk_forward_folds(observations)
        primary = _evaluate_feature(
            observations,
            folds,
            feature_name=PRIMARY_FEATURE,
            target_name=PRIMARY_TARGET,
        )
        secondary_targets = [
            _evaluate_feature(observations, folds, feature_name=PRIMARY_FEATURE, target_name=target)
            for target in TARGETS
            if target != PRIMARY_TARGET
        ]
        exempt = _evaluate_feature(
            observations,
            folds,
            feature_name=SECONDARY_FEATURE,
            target_name=PRIMARY_TARGET,
        )
        verdict, verdict_summary = _verdict(
            trading_days=trading_days,
            primary=primary,
        )
        return {
            "status": "research_only",
            "mode": "shadow",
            "automatic_activation": False,
            "activation_ready": False,
            "applied_impact": 0,
            "experiment_id": EXPERIMENT_ID,
            "verdict": verdict,
            "verdict_summary": verdict_summary,
            "feature_family": "short_volume",
            "not_short_interest": True,
            "provenance": "FINRA_OFF_EXCHANGE",
            "exchange_short_volume_included": False,
            "legal_gate": dict(LEGAL_GATE),
            "pre_registration": _pre_registration(
                short_interest_feature_present=self._short_interest_feature_present
            ),
            "sample": {
                "observations": len(observations),
                "tickers": len(tickers),
                "trading_days": trading_days,
                "minimum_trading_days": MIN_TRADING_DAYS,
                "history_sufficient": trading_days >= MIN_TRADING_DAYS,
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
            "primary": primary,
            "secondary_targets": secondary_targets,
            "exempt_share_vs_primary_target": exempt,
            "short_interest_comparison": {
                "present": self._short_interest_feature_present,
                "policy": SHORT_INTEREST_COMPARISON_POLICY,
                "result": (
                    "Not compared; OmniTrade has no short-interest feature."
                    if not self._short_interest_feature_present
                    else "Comparison allowed only against the existing short-interest feature."
                ),
            },
            "deployment_guard": {
                "automatic_config_changes": False,
                "live_recommendation_changes": False,
                "commercial_shipping": False,
                "message": (
                    "Shadow-only. This analysis never writes live scores, recommendations, "
                    "or a commercial shipping path."
                ),
            },
        }


def empty_research_payload(*, reason: str) -> dict[str, Any]:
    payload = FinraShortVolumeResearchService(observations=()).build_payload()
    payload["verdict"] = "data_blocked"
    payload["verdict_summary"] = reason
    payload["sample"]["history_sufficient"] = False
    return payload


__all__ = [
    "EXPERIMENT_ID",
    "FinraShortVolumeObservation",
    "FinraShortVolumeResearchService",
    "WalkForwardFold",
    "build_observations",
    "build_walk_forward_folds",
    "empty_research_payload",
]
