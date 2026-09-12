from __future__ import annotations

from dataclasses import asdict, dataclass, field

from config.etf import ETF_OMNISCORE_WEIGHTS, EtfOmniScoreWeights
from domain.etf.metrics import EtfPerformanceMetrics
from domain.etf.models import EtfHoldingsSnapshot, EtfProfile


@dataclass(frozen=True)
class EtfScoreComponent:
    key: str
    label: str
    score: float | None
    weight: float
    applied_weight: float
    available: bool
    summary: str
    inputs: dict[str, float | str | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EtfOmniScore:
    score: float | None
    components: tuple[EtfScoreComponent, ...]
    predictive: bool = False
    note: str = "ETF OmniScore is a transparent research composite, not a validated forecast."

    def to_dict(self) -> dict[str, object]:
        return {
            "score": self.score,
            "predictive": self.predictive,
            "note": self.note,
            "components": [component.to_dict() for component in self.components],
        }


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _momentum_score(metrics: EtfPerformanceMetrics) -> tuple[float | None, dict[str, float | str | None], str]:
    samples: list[float] = []
    inputs: dict[str, float | str | None] = {
        "return_1m": metrics.return_1m,
        "return_3m": metrics.return_3m,
        "return_1y": metrics.return_1y,
    }
    if metrics.return_1m is not None:
        samples.append(_clamp(50 + metrics.return_1m * 2.0))
    if metrics.return_3m is not None:
        samples.append(_clamp(50 + metrics.return_3m))
    if metrics.return_1y is not None:
        samples.append(_clamp(50 + metrics.return_1y * 0.4))
    if not samples:
        return None, inputs, "Momentum is unavailable because return history is insufficient."
    score = sum(samples) / len(samples)
    return score, inputs, "Momentum uses available multi-period returns; missing windows are omitted."


def _risk_score(metrics: EtfPerformanceMetrics) -> tuple[float | None, dict[str, float | str | None], str]:
    samples: list[float] = []
    inputs: dict[str, float | str | None] = {
        "annualized_volatility": metrics.annualized_volatility,
        "maximum_drawdown": metrics.maximum_drawdown,
        "downside_volatility": metrics.downside_volatility,
        "sharpe_ratio": metrics.sharpe_ratio,
    }
    if metrics.annualized_volatility is not None:
        samples.append(_clamp(100 - metrics.annualized_volatility * 2.0))
    if metrics.maximum_drawdown is not None:
        samples.append(_clamp(100 + metrics.maximum_drawdown * 2.0))
    if metrics.downside_volatility is not None:
        samples.append(_clamp(100 - metrics.downside_volatility * 2.5))
    if metrics.sharpe_ratio is not None:
        samples.append(_clamp(50 + metrics.sharpe_ratio * 15.0))
    if not samples:
        return None, inputs, "Risk metrics are unavailable because price history is insufficient."
    return sum(samples) / len(samples), inputs, "Risk uses volatility, drawdown, and Sharpe only when each series is complete."


def _liquidity_score(profile: EtfProfile) -> tuple[float | None, dict[str, float | str | None], str]:
    volume = profile.average_volume
    inputs: dict[str, float | str | None] = {"average_volume": volume}
    if volume is None:
        return None, inputs, "Liquidity is unavailable because average volume is missing."
    if volume >= 20_000_000:
        score = 90.0
    elif volume >= 5_000_000:
        score = 75.0
    elif volume >= 1_000_000:
        score = 60.0
    elif volume >= 250_000:
        score = 45.0
    else:
        score = 25.0
    return score, inputs, "Liquidity is scored from average daily volume only."


def _fund_quality_score(
    profile: EtfProfile,
    holdings: EtfHoldingsSnapshot | None,
) -> tuple[float | None, dict[str, float | str | None], str]:
    samples: list[float] = []
    concentration = holdings.top_10_concentration if holdings is not None else None
    inputs: dict[str, float | str | None] = {
        "expense_ratio": profile.expense_ratio,
        "aum": profile.aum,
        "top_10_concentration": concentration,
    }
    if profile.expense_ratio is not None:
        bps = profile.expense_ratio * 100 if profile.expense_ratio < 1 else profile.expense_ratio
        # expense_ratio stored as fraction (0.0003) or percent (0.03 / 0.94)
        if profile.expense_ratio > 1:
            bps = profile.expense_ratio
        elif profile.expense_ratio > 0.05:
            bps = profile.expense_ratio
        else:
            bps = profile.expense_ratio * 100
        samples.append(_clamp(95 - bps * 80))
    if profile.aum is not None:
        if profile.aum >= 50_000_000_000:
            samples.append(90.0)
        elif profile.aum >= 10_000_000_000:
            samples.append(80.0)
        elif profile.aum >= 1_000_000_000:
            samples.append(65.0)
        elif profile.aum >= 100_000_000:
            samples.append(45.0)
        else:
            samples.append(25.0)
    if concentration is not None:
        samples.append(_clamp(100 - concentration * 80))
    if not samples:
        return None, inputs, "Fund quality is unavailable because expense ratio, AUM, and concentration are missing."
    return sum(samples) / len(samples), inputs, "Fund quality omits any missing sub-factor instead of scoring it as zero."


def _flows_score() -> tuple[float | None, dict[str, float | str | None], str]:
    return None, {}, "Fund-flow data is not provided by the configured ETF providers."


def _underlying_score(exposure_score: float | None, coverage_weight: float | None) -> tuple[float | None, dict[str, float | str | None], str]:
    inputs: dict[str, float | str | None] = {
        "underlying_signal_score": exposure_score,
        "coverage_weight": coverage_weight,
    }
    if exposure_score is None:
        return None, inputs, "Underlying exposure is unavailable until stock signals overlap ETF holdings."
    return _clamp(exposure_score), inputs, "Underlying exposure is stock signal strength weighted by known holdings."


def build_etf_omni_score(
    profile: EtfProfile,
    metrics: EtfPerformanceMetrics,
    holdings: EtfHoldingsSnapshot | None,
    *,
    underlying_exposure_score: float | None = None,
    underlying_coverage_weight: float | None = None,
    weights: EtfOmniScoreWeights = ETF_OMNISCORE_WEIGHTS,
) -> EtfOmniScore:
    raw_components = [
        ("momentum", "Momentum", weights.momentum, *_momentum_score(metrics)),
        ("risk", "Risk", weights.risk, *_risk_score(metrics)),
        ("liquidity", "Liquidity", weights.liquidity, *_liquidity_score(profile)),
        ("fund_quality", "Fund Quality", weights.fund_quality, *_fund_quality_score(profile, holdings)),
        ("flows", "Flows", weights.flows, *_flows_score()),
        (
            "underlying_exposure",
            "Underlying Exposure",
            weights.underlying_exposure,
            *_underlying_score(underlying_exposure_score, underlying_coverage_weight),
        ),
    ]
    available_weight = sum(weight for _, _, weight, score, _, _ in raw_components if score is not None)
    components: list[EtfScoreComponent] = []
    weighted_total = 0.0
    for key, label, weight, score, inputs, summary in raw_components:
        applied = 0.0 if score is None or available_weight <= 0 else weight / available_weight
        if score is not None:
            weighted_total += score * applied
        components.append(
            EtfScoreComponent(
                key=key,
                label=label,
                score=None if score is None else round(score, 2),
                weight=weight,
                applied_weight=round(applied, 4),
                available=score is not None,
                summary=summary,
                inputs=inputs,
            )
        )
    overall = None if available_weight <= 0 else round(weighted_total, 2)
    return EtfOmniScore(score=overall, components=tuple(components))


__all__ = ["EtfOmniScore", "EtfScoreComponent", "build_etf_omni_score"]
