from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

from domain.etf.models import AllocationSlice, EtfHolding, EtfProfile


@dataclass(frozen=True)
class HoldingMatch:
    ticker: str | None
    name: str | None
    weight_a: float | None
    weight_b: float | None
    overlap_weight: float | None

    def to_dict(self) -> dict[str, float | str | None]:
        return asdict(self)


def holding_key(holding: EtfHolding) -> str | None:
    if holding.holding_ticker:
        return holding.holding_ticker.upper()
    if holding.holding_name:
        return f"name:{holding.holding_name.strip().upper()}"
    return None


def _weight_map(holdings: Sequence[EtfHolding]) -> dict[str, EtfHolding]:
    mapped: dict[str, EtfHolding] = {}
    for holding in holdings:
        key = holding_key(holding)
        if key is None:
            continue
        mapped[key] = holding
    return mapped


def pairwise_overlap(holdings_a: Sequence[EtfHolding], holdings_b: Sequence[EtfHolding]) -> float:
    """Return overlap as a 0-1 fraction: sum(min(weight_a, weight_b)) across shared holdings."""
    map_a = _weight_map(holdings_a)
    map_b = _weight_map(holdings_b)
    total = 0.0
    for key in set(map_a) & set(map_b):
        weight_a = map_a[key].weight
        weight_b = map_b[key].weight
        if weight_a is None or weight_b is None:
            continue
        total += min(weight_a, weight_b)
    return round(total, 10)


def shared_and_unique(
    holdings_a: Sequence[EtfHolding],
    holdings_b: Sequence[EtfHolding],
) -> tuple[list[HoldingMatch], list[HoldingMatch], list[HoldingMatch]]:
    map_a = _weight_map(holdings_a)
    map_b = _weight_map(holdings_b)
    shared: list[HoldingMatch] = []
    unique_a: list[HoldingMatch] = []
    unique_b: list[HoldingMatch] = []
    for key in sorted(set(map_a) | set(map_b)):
        left = map_a.get(key)
        right = map_b.get(key)
        if left and right:
            overlap = None
            if left.weight is not None and right.weight is not None:
                overlap = min(left.weight, right.weight)
            shared.append(
                HoldingMatch(
                    ticker=left.holding_ticker or right.holding_ticker,
                    name=left.holding_name or right.holding_name,
                    weight_a=left.weight,
                    weight_b=right.weight,
                    overlap_weight=overlap,
                )
            )
        elif left:
            unique_a.append(
                HoldingMatch(
                    ticker=left.holding_ticker,
                    name=left.holding_name,
                    weight_a=left.weight,
                    weight_b=None,
                    overlap_weight=None,
                )
            )
        elif right:
            unique_b.append(
                HoldingMatch(
                    ticker=right.holding_ticker,
                    name=right.holding_name,
                    weight_a=None,
                    weight_b=right.weight,
                    overlap_weight=None,
                )
            )
    shared.sort(key=lambda item: (item.overlap_weight is None, -(item.overlap_weight or 0.0)))
    unique_a.sort(key=lambda item: (item.weight_a is None, -(item.weight_a or 0.0)))
    unique_b.sort(key=lambda item: (item.weight_b is None, -(item.weight_b or 0.0)))
    return shared, unique_a, unique_b


def allocation_compare(
    left: Sequence[AllocationSlice],
    right: Sequence[AllocationSlice],
) -> list[dict[str, float | str | None]]:
    left_map = {item.label: item.weight for item in left}
    right_map = {item.label: item.weight for item in right}
    labels = sorted(set(left_map) | set(right_map))
    rows: list[dict[str, float | str | None]] = []
    for label in labels:
        weight_a = left_map.get(label)
        weight_b = right_map.get(label)
        delta = None if weight_a is None or weight_b is None else weight_a - weight_b
        rows.append({"label": label, "weight_a": weight_a, "weight_b": weight_b, "delta": delta})
    rows.sort(key=lambda item: -(max(item["weight_a"] or 0.0, item["weight_b"] or 0.0)))
    return rows


def profile_compare_row(profile: EtfProfile | None) -> dict[str, object | None]:
    if profile is None:
        return {
            "ticker": None,
            "name": None,
            "expense_ratio": None,
            "aum": None,
            "average_volume": None,
            "dividend_yield": None,
            "issuer": None,
            "category": None,
        }
    return {
        "ticker": profile.ticker,
        "name": profile.name,
        "expense_ratio": profile.expense_ratio,
        "aum": profile.aum,
        "average_volume": profile.average_volume,
        "dividend_yield": profile.dividend_yield,
        "issuer": profile.issuer,
        "category": profile.category,
    }


__all__ = [
    "HoldingMatch",
    "allocation_compare",
    "holding_key",
    "pairwise_overlap",
    "profile_compare_row",
    "shared_and_unique",
]
