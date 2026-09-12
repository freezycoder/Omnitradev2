from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


DATA_UNAVAILABLE = "Data unavailable"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def optional_int(value: Any) -> int | None:
    number = optional_float(value)
    if number is None:
        return None
    return int(number)


def optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class AllocationSlice:
    label: str
    weight: float
    source: str | None = None


@dataclass(frozen=True)
class EtfHolding:
    etf_ticker: str
    holding_ticker: str | None
    holding_name: str | None
    weight: float | None
    shares: float | None = None
    as_of: str | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EtfHoldingsSnapshot:
    etf_ticker: str
    captured_at: str
    source: str | None
    holdings: tuple[EtfHolding, ...] = field(default_factory=tuple)
    sector_allocation: tuple[AllocationSlice, ...] = field(default_factory=tuple)
    geographic_allocation: tuple[AllocationSlice, ...] = field(default_factory=tuple)

    @property
    def holdings_count(self) -> int:
        return len(self.holdings)

    @property
    def top_5_concentration(self) -> float | None:
        return _concentration(self.holdings, 5)

    @property
    def top_10_concentration(self) -> float | None:
        return _concentration(self.holdings, 10)

    def to_dict(self) -> dict[str, Any]:
        return {
            "etf_ticker": self.etf_ticker,
            "captured_at": self.captured_at,
            "source": self.source,
            "holdings": [holding.to_dict() for holding in self.holdings],
            "holdings_count": self.holdings_count,
            "top_5_concentration": self.top_5_concentration,
            "top_10_concentration": self.top_10_concentration,
            "sector_allocation": [asdict(item) for item in self.sector_allocation],
            "geographic_allocation": [asdict(item) for item in self.geographic_allocation],
        }


@dataclass(frozen=True)
class EtfProfile:
    ticker: str
    name: str | None = None
    issuer: str | None = None
    asset_class: str | None = None
    category: str | None = None
    description: str | None = None
    expense_ratio: float | None = None
    aum: float | None = None
    average_volume: float | None = None
    dividend_yield: float | None = None
    inception_date: str | None = None
    holdings_count: int | None = None
    geographic_exposure: tuple[AllocationSlice, ...] = field(default_factory=tuple)
    sector_exposure: tuple[AllocationSlice, ...] = field(default_factory=tuple)
    source: str | None = None
    quote_type: str | None = None
    updated_at: str = field(default_factory=utc_now_iso)
    unavailable_fields: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["geographic_exposure"] = [asdict(item) for item in self.geographic_exposure]
        payload["sector_exposure"] = [asdict(item) for item in self.sector_exposure]
        return payload


@dataclass(frozen=True)
class EtfFlowSnapshot:
    ticker: str
    net_flow: float | None = None
    as_of: str | None = None
    source: str | None = None
    available: bool = False
    unavailable_reason: str = DATA_UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _concentration(holdings: tuple[EtfHolding, ...], count: int) -> float | None:
    weights = [holding.weight for holding in holdings if holding.weight is not None]
    if not weights:
        return None
    return float(sum(sorted(weights, reverse=True)[:count]))


__all__ = [
    "AllocationSlice",
    "DATA_UNAVAILABLE",
    "EtfFlowSnapshot",
    "EtfHolding",
    "EtfHoldingsSnapshot",
    "EtfProfile",
    "optional_float",
    "optional_int",
    "optional_str",
    "utc_now_iso",
]
