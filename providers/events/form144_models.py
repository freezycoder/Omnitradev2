from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
from typing import Any, Literal


SourceKind = Literal["edgar_form144_xml", "fixture", "json"]
Form4SourceKind = Literal[
    "section16_keep_json",
    "edgar_form4_xml",
    "sec_event_bundle",
    "fixture",
    "json",
]


@dataclass(frozen=True)
class ProposedSaleNotice:
    accession_number: str
    ticker: str | None
    issuer_cik: str | None
    issuer_name: str | None
    filer_cik: str | None
    filer_name: str | None
    relationship: str | None
    filed_at: str
    approx_sale_date: str | None
    proposed_units: float | None
    aggregate_market_value: float | None
    broker: str | None
    prior_3m_units: float | None
    prior_3m_proceeds: float | None
    securities_class: str | None
    source: SourceKind = "edgar_form144_xml"
    affiliate_eligible: bool = False
    affiliate_reason: str = "unchecked"

    @property
    def intent_date(self) -> str:
        return self.approx_sale_date or self.filed_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProposedSaleNotice":
        values = dict(payload)
        values.pop("intent_date", None)
        return cls(**values)


@dataclass(frozen=True)
class Form4Sale:
    accession_number: str
    ticker: str | None
    issuer_cik: str | None
    filer_cik: str | None
    filer_name: str | None
    filed_at: str
    transaction_date: str
    transaction_code: str
    acquired_disposed: str | None
    shares: float | None
    value_usd: float | None
    source: Form4SourceKind = "fixture"
    is_derivative: bool = False

    @property
    def event_date(self) -> str:
        return self.transaction_date or self.filed_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Form4Sale":
        values = dict(payload)
        values.pop("event_date", None)
        allowed = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in values.items() if key in allowed})


@dataclass(frozen=True)
class TickerDayIntensity:
    ticker: str
    as_of: str
    notice_count: int
    affiliate_count: int
    proposed_units: float
    cluster: bool
    filer_ciks: tuple[str, ...]
    accession_numbers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["filer_ciks"] = list(self.filer_ciks)
        payload["accession_numbers"] = list(self.accession_numbers)
        return payload


@dataclass(frozen=True)
class Form144ClusterEvent:
    ticker: str
    as_of: str
    window_start: str
    affiliate_count: int
    filer_ciks: tuple[str, ...]
    proposed_units: float
    accession_numbers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["filer_ciks"] = list(self.filer_ciks)
        payload["accession_numbers"] = list(self.accession_numbers)
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


def normalize_cik(value: str | None) -> str | None:
    if value is None:
        return None
    digits = "".join(char for char in str(value) if char.isdigit())
    if not digits:
        return None
    return digits.zfill(10)


def normalize_ticker(value: str | None) -> str | None:
    text = str(value or "").upper().strip()
    return text or None
