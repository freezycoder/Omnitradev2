from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Literal


PurposeClass = Literal["activist", "ambiguous", "passive_excluded", "financing_excluded"]
FormKind = Literal["SC 13D", "SC 13D/A", "SC 13G", "SC 13G/A"]


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


def normalize_form(value: str | None) -> FormKind | None:
    text = str(value or "").upper().replace("SCHEDULE", "SC").strip()
    text = " ".join(text.split())
    mapping = {
        "SC 13D": "SC 13D",
        "13D": "SC 13D",
        "SC13D": "SC 13D",
        "SC 13D/A": "SC 13D/A",
        "13D/A": "SC 13D/A",
        "SC13D/A": "SC 13D/A",
        "SC 13G": "SC 13G",
        "13G": "SC 13G",
        "SC13G": "SC 13G",
        "SC 13G/A": "SC 13G/A",
        "13G/A": "SC 13G/A",
        "SC13G/A": "SC 13G/A",
    }
    return mapping.get(text)  # type: ignore[return-value]


@dataclass(frozen=True)
class Sc13dFiling:
    accession_number: str
    form: str
    filed_at: str
    ticker: str
    issuer_cik: str | None
    issuer_name: str | None
    reporting_cik: str | None
    reporting_name: str | None
    url: str
    purpose_text: str
    percent_of_class: float | None
    prior_percent_of_class: float | None = None
    conversion_text_flag: bool = False
    conversion_prior_13g: bool = False
    source: str = "sec_edgar"
    raw_excerpt: str = ""

    @property
    def conversion_13g_to_13d(self) -> bool:
        return bool(self.conversion_text_flag or self.conversion_prior_13g)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conversion_13g_to_13d"] = self.conversion_13g_to_13d
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Sc13dFiling":
        values = dict(payload)
        values.pop("conversion_13g_to_13d", None)
        return cls(**values)


@dataclass(frozen=True)
class ClassifiedSc13dEvent:
    filing: Sc13dFiling
    purpose_class: PurposeClass
    matched_groups: tuple[str, ...]
    matched_phrases: tuple[str, ...]
    exclude_reason: str | None = None

    @property
    def ticker(self) -> str:
        return self.filing.ticker.upper().strip()

    @property
    def filed_at(self) -> str:
        return self.filing.filed_at

    @property
    def accession_number(self) -> str:
        return self.filing.accession_number

    def to_dict(self) -> dict[str, Any]:
        return {
            "filing": self.filing.to_dict(),
            "purpose_class": self.purpose_class,
            "matched_groups": list(self.matched_groups),
            "matched_phrases": list(self.matched_phrases),
            "exclude_reason": self.exclude_reason,
            "conversion_13g_to_13d": self.filing.conversion_13g_to_13d,
        }


@dataclass(frozen=True)
class Form4BuyEvent:
    ticker: str
    filed_at: str
    accession_number: str
    category: str = "insider_purchase"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParsedSc13dDocument:
    purpose_text: str
    percent_of_class: float | None
    reporting_cik: str | None
    reporting_name: str | None
    issuer_name: str | None
    conversion_text_flag: bool
    matched_conversion_phrases: tuple[str, ...] = field(default_factory=tuple)


__all__ = [
    "ClassifiedSc13dEvent",
    "Form4BuyEvent",
    "FormKind",
    "ParsedSc13dDocument",
    "PurposeClass",
    "Sc13dFiling",
    "normalize_form",
    "parse_iso_date",
]
