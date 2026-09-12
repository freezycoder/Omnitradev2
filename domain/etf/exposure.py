from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from domain.etf.models import EtfHolding, EtfProfile


@dataclass(frozen=True)
class StockEtfExposure:
    etf_ticker: str
    etf_name: str | None
    weight: float | None
    aum: float | None
    expense_ratio: float | None
    source: str | None = None

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)


@dataclass(frozen=True)
class ContributingHolding:
    ticker: str
    weight: float
    signal_score: float | None
    contribution: float

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)


@dataclass(frozen=True)
class UnderlyingSignalExposure:
    etf_ticker: str
    etf_name: str | None
    exposure_score: float
    contributing_holdings: tuple[ContributingHolding, ...]
    coverage_weight: float

    def to_dict(self) -> dict[str, object]:
        return {
            "etf_ticker": self.etf_ticker,
            "etf_name": self.etf_name,
            "exposure_score": self.exposure_score,
            "coverage_weight": self.coverage_weight,
            "contributing_holdings": [item.to_dict() for item in self.contributing_holdings],
        }


def reverse_etf_exposure(
    stock_ticker: str,
    holdings: Sequence[EtfHolding],
    profiles: Mapping[str, EtfProfile],
    *,
    min_weight: float = 0.005,
) -> list[StockEtfExposure]:
    target = stock_ticker.upper().strip()
    rows: list[StockEtfExposure] = []
    for holding in holdings:
        if (holding.holding_ticker or "").upper() != target:
            continue
        if holding.weight is None or holding.weight < min_weight:
            continue
        profile = profiles.get(holding.etf_ticker)
        rows.append(
            StockEtfExposure(
                etf_ticker=holding.etf_ticker,
                etf_name=profile.name if profile else None,
                weight=holding.weight,
                aum=profile.aum if profile else None,
                expense_ratio=profile.expense_ratio if profile else None,
                source=holding.source,
            )
        )
    rows.sort(key=lambda item: (item.weight is None, -(item.weight or 0.0), item.etf_ticker))
    return rows


def thematic_exposure_score(
    holdings: Sequence[EtfHolding],
    stock_scores: Mapping[str, float],
) -> tuple[float | None, float, tuple[ContributingHolding, ...]]:
    """Return (weighted signal score, coverage weight, contributors).

    Score is sum(stock_signal_strength * ETF holding weight) / covered weight.
    Missing stock scores are excluded rather than treated as zero.
    """
    contributors: list[ContributingHolding] = []
    weighted = 0.0
    covered = 0.0
    for holding in holdings:
        ticker = (holding.holding_ticker or "").upper()
        if not ticker or holding.weight is None or holding.weight <= 0:
            continue
        if ticker not in stock_scores:
            continue
        score = float(stock_scores[ticker])
        contribution = score * holding.weight
        weighted += contribution
        covered += holding.weight
        contributors.append(
            ContributingHolding(
                ticker=ticker,
                weight=holding.weight,
                signal_score=score,
                contribution=contribution,
            )
        )
    contributors.sort(key=lambda item: item.contribution, reverse=True)
    if covered <= 0:
        return None, 0.0, ()
    return weighted / covered, covered, tuple(contributors[:10])


__all__ = [
    "ContributingHolding",
    "StockEtfExposure",
    "UnderlyingSignalExposure",
    "reverse_etf_exposure",
    "thematic_exposure_score",
]
