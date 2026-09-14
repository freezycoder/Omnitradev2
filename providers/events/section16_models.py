from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal


Direction = Literal["P", "S"]
SourceKind = Literal["sec_quarterly_zip", "edgar_form4_xml", "tracefour"]


@dataclass(frozen=True)
class InsiderTransaction:
    accession_number: str
    ticker: str
    issuer_cik: str | None
    issuer_name: str | None
    owner_cik: str | None
    owner_name: str | None
    owner_title: str | None
    is_director: bool
    is_officer: bool
    is_ten_percent_owner: bool
    transaction_date: str
    filed_at: str
    transaction_code: str
    acquired_disposed: str | None
    shares: float | None
    price_per_share: float | None
    value_usd: float | None
    is_10b5_1: bool
    is_derivative: bool
    source: SourceKind
    footnote_ids: tuple[str, ...] = ()
    document_type: str | None = None

    @property
    def direction(self) -> Direction | None:
        code = self.transaction_code.upper().strip()
        if code in {"P", "S"}:
            return code
        return None

    @property
    def signed_value_usd(self) -> float:
        value = float(self.value_usd or 0.0)
        if self.transaction_code.upper().strip() == "S":
            return -abs(value)
        return abs(value)

    @property
    def signed_shares(self) -> float:
        shares = float(self.shares or 0.0)
        if self.transaction_code.upper().strip() == "S":
            return -abs(shares)
        return abs(shares)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InsiderTransaction":
        values = dict(payload)
        footnotes = values.get("footnote_ids") or ()
        values["footnote_ids"] = tuple(str(item) for item in footnotes)
        return cls(**values)


@dataclass(frozen=True)
class ClusterEvent:
    ticker: str
    direction: Direction
    as_of: str
    window_start: str
    insider_count: int
    insider_ciks: tuple[str, ...]
    total_value_usd: float
    accession_numbers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["insider_ciks"] = list(self.insider_ciks)
        payload["accession_numbers"] = list(self.accession_numbers)
        return payload


@dataclass(frozen=True)
class StreakEvent:
    ticker: str
    owner_cik: str
    owner_name: str | None
    direction: Direction
    as_of: str
    weeks: int
    streak_value_usd: float
    week_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["week_keys"] = list(self.week_keys)
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
