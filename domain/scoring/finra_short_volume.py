from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.settings import FINRA_SHORT_VOLUME_MODE, FINRA_SHORT_VOLUME_PROVENANCE
from providers.market.finra_short_volume_client import FinraShortVolumeRow


FEATURE_FAMILY = "short_volume"
FEATURE_FAMILY_LABEL = "FINRA off-exchange short volume"
NOT_SHORT_INTEREST_LABEL = "Not bi-monthly short interest"

LEGAL_GATE = {
    "source": "FINRA Short Sale Volume (Reg SHO daily CNMSshvol)",
    "catalog_url": "https://www.finra.org/finra-data/browse-catalog/short-sale-volume",
    "adapter_docs_url": "https://verdenroz.github.io/finance-query/library/providers/finra/",
    "use_class": "non_commercial_research",
    "commercial_use_allowed": False,
    "shipping_allowed": False,
    "requires_human_approval": True,
    "approval_owner": "Alvaro",
    "notes": (
        "FINRA publishes aggregated short-sale volume by security for TRF/ADF/ORF. "
        "The files are free for non-commercial use, are not bi-monthly short interest, "
        "and are not consolidated with exchange short volume. Commercial shipping is "
        "blocked until an explicit agreement and Alvaro approval exist."
    ),
}

PERMANENT_COVERAGE_CAVEAT = (
    "FINRA_OFF_EXCHANGE only: exchange short volume is absent from CNMSshvol, "
    "so short_ratio is an off-exchange facility share, not a consolidated short-volume ratio."
)


@dataclass(frozen=True)
class FinraShortVolumeView:
    mode: str
    status: str
    applied_impact: int
    coverage_score: int
    feature_family: str
    feature_label: str
    provenance: str
    facility: str
    as_of_date: str | None
    symbol: str | None
    short_volume: float | None
    short_exempt_volume: float | None
    total_volume: float | None
    short_ratio: float | None
    exempt_share: float | None
    exchange_short_volume_included: bool
    short_interest_feature_present: bool
    not_short_interest: bool
    legal_gate: dict[str, Any]
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _round_volume(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def build_finra_short_volume_view(
    row: FinraShortVolumeRow | None,
    *,
    short_interest_feature_present: bool = False,
    warning: str | None = None,
) -> FinraShortVolumeView:
    warnings = [PERMANENT_COVERAGE_CAVEAT]
    if warning:
        warnings.append(warning)
    if short_interest_feature_present:
        warnings.append(
            "A separate short-interest feature exists in this snapshot and was not combined with short volume."
        )
    else:
        warnings.append(
            "No short-interest feature is present in OmniTrade; this experiment does not invent one."
        )

    if row is None or row.short_ratio is None:
        message = warning or "FINRA off-exchange short volume is unavailable for this ticker."
        return build_unavailable_finra_short_volume_view(
            message,
            short_interest_feature_present=short_interest_feature_present,
        )

    short_ratio = _round_ratio(row.short_ratio)
    exempt_share = _round_ratio(row.exempt_share)
    evidence = [
        f"{row.symbol} CNMS short_ratio={short_ratio:.4f} on {row.as_of_date.isoformat()}.",
        f"Exempt share={exempt_share:.4f}; ShortVolume={row.short_volume:.1f}; TotalVolume={row.total_volume:.1f}.",
        PERMANENT_COVERAGE_CAVEAT,
        "This is daily Reg SHO short volume, not bi-monthly short interest.",
    ]
    summary = (
        f"Off-exchange short volume was {short_ratio:.1%} of FINRA CNMS total volume "
        f"on {row.as_of_date.isoformat()}. This shadow factor does not change the live recommendation."
    )
    return FinraShortVolumeView(
        mode=FINRA_SHORT_VOLUME_MODE,
        status="available",
        applied_impact=0,
        coverage_score=100,
        feature_family=FEATURE_FAMILY,
        feature_label=FEATURE_FAMILY_LABEL,
        provenance=row.provenance,
        facility=row.facility,
        as_of_date=row.as_of_date.isoformat(),
        symbol=row.symbol,
        short_volume=_round_volume(row.short_volume),
        short_exempt_volume=_round_volume(row.short_exempt_volume),
        total_volume=_round_volume(row.total_volume),
        short_ratio=short_ratio,
        exempt_share=exempt_share,
        exchange_short_volume_included=False,
        short_interest_feature_present=short_interest_feature_present,
        not_short_interest=True,
        legal_gate=dict(LEGAL_GATE),
        summary=summary,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_finra_short_volume_view(
    message: str,
    *,
    short_interest_feature_present: bool = False,
) -> FinraShortVolumeView:
    warnings = [message, PERMANENT_COVERAGE_CAVEAT]
    if not short_interest_feature_present:
        warnings.append(
            "No short-interest feature is present in OmniTrade; this experiment does not invent one."
        )
    return FinraShortVolumeView(
        mode=FINRA_SHORT_VOLUME_MODE,
        status="unavailable",
        applied_impact=0,
        coverage_score=0,
        feature_family=FEATURE_FAMILY,
        feature_label=FEATURE_FAMILY_LABEL,
        provenance=FINRA_SHORT_VOLUME_PROVENANCE,
        facility="CNMS",
        as_of_date=None,
        symbol=None,
        short_volume=None,
        short_exempt_volume=None,
        total_volume=None,
        short_ratio=None,
        exempt_share=None,
        exchange_short_volume_included=False,
        short_interest_feature_present=short_interest_feature_present,
        not_short_interest=True,
        legal_gate=dict(LEGAL_GATE),
        summary=message,
        warnings=list(dict.fromkeys(warnings)),
        updated_at=datetime.now(UTC).isoformat(),
    )


def finra_short_volume_view_from_dict(payload: dict[str, Any] | None) -> FinraShortVolumeView:
    if not isinstance(payload, dict):
        return build_unavailable_finra_short_volume_view(
            "The cached snapshot predates FINRA short-volume analysis."
        )
    values = dict(payload)
    values.setdefault("mode", FINRA_SHORT_VOLUME_MODE)
    values.setdefault("applied_impact", 0)
    values.setdefault("feature_family", FEATURE_FAMILY)
    values.setdefault("feature_label", FEATURE_FAMILY_LABEL)
    values.setdefault("provenance", FINRA_SHORT_VOLUME_PROVENANCE)
    values.setdefault("not_short_interest", True)
    values.setdefault("exchange_short_volume_included", False)
    values.setdefault("legal_gate", dict(LEGAL_GATE))
    values["applied_impact"] = 0
    allowed = {field.name for field in FinraShortVolumeView.__dataclass_fields__.values()}
    return FinraShortVolumeView(**{key: value for key, value in values.items() if key in allowed})


__all__ = [
    "FEATURE_FAMILY",
    "FEATURE_FAMILY_LABEL",
    "LEGAL_GATE",
    "NOT_SHORT_INTEREST_LABEL",
    "PERMANENT_COVERAGE_CAVEAT",
    "FinraShortVolumeView",
    "build_finra_short_volume_view",
    "build_unavailable_finra_short_volume_view",
    "finra_short_volume_view_from_dict",
]
