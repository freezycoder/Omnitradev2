from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal


Direction = Literal["entry", "exit"]
SourceKind = Literal["sec_form13f_zip", "fixture"]


@dataclass(frozen=True)
class HoldingPosition:
    accession_number: str
    manager_cik: str
    manager_name: str | None
    reportable_quarter: str
    filed_at: str
    cusip: str
    ticker: str | None
    issuer_name: str | None
    title_of_class: str | None
    shares: float | None
    value_usd: float | None
    put_call: str | None
    shares_type: str | None
    submission_type: str | None
    is_amendment: bool
    source: SourceKind = "sec_form13f_zip"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "HoldingPosition":
        return cls(**payload)


@dataclass(frozen=True)
class ManagerQuarter:
    manager_cik: str
    manager_name: str | None
    reportable_quarter: str
    filed_at: str
    aum_usd: float
    tickers: tuple[str, ...]
    notable: bool
    passive: bool
    notable_reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tickers"] = list(self.tickers)
        return payload


@dataclass(frozen=True)
class ClusterEvent:
    ticker: str
    direction: Direction
    reportable_quarter: str
    event_date: str
    notable_count: int
    manager_ciks: tuple[str, ...]
    filing_dates: tuple[str, ...]
    etf_churn_suspect: bool
    passive_enter_or_exit_count: int
    reconstitution_window: str | None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["manager_ciks"] = list(self.manager_ciks)
        payload["filing_dates"] = list(self.filing_dates)
        return payload


@dataclass(frozen=True)
class StreakEvent:
    ticker: str
    reportable_quarter: str
    event_date: str
    quarters: int
    quarter_keys: tuple[str, ...]
    net_notable_adds: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quarter_keys"] = list(self.quarter_keys)
        return payload


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
