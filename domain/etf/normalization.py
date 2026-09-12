from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Iterable

from domain.etf.models import (
    AllocationSlice,
    EtfHolding,
    EtfHoldingsSnapshot,
    EtfProfile,
    optional_float,
    optional_str,
    utc_now_iso,
)


TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
NON_SECURITY_NAMES = {
    "CASH",
    "CASH AND EQUIVALENTS",
    "CASH AND/OR DERIVATIVES",
    "OTHER",
    "NET OTHER ASSETS",
    "N/A",
}


def normalize_ticker(value: Any) -> str | None:
    text = optional_str(value)
    if text is None:
        return None
    ticker = text.upper().replace(" ", "")
    if not TICKER_PATTERN.match(ticker):
        return None
    if ticker in {"CASH", "OTHER"}:
        return None
    return ticker


def _as_weight(value: Any, *, treat_as_percent: bool) -> float | None:
    number = optional_float(value)
    if number is None:
        return None
    weight = number / 100.0 if treat_as_percent else number
    if weight < 0:
        return None
    return weight


def infer_percent_scale(raw_weights: Iterable[Any]) -> bool:
    values = [optional_float(value) for value in raw_weights]
    present = [value for value in values if value is not None]
    if not present:
        return False
    return max(present) > 1.5


def normalize_allocation(items: Iterable[dict[str, Any]] | dict[str, Any] | None, source: str | None) -> tuple[AllocationSlice, ...]:
    if not items:
        return ()
    rows: list[tuple[str, Any]]
    if isinstance(items, dict):
        rows = [(str(key), value) for key, value in items.items()]
    else:
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            label = optional_str(item.get("label") or item.get("name") or item.get("sector") or item.get("country") or item.get("exposure"))
            if label is None:
                continue
            rows.append((label, item.get("weight") if "weight" in item else item.get("percent") if "percent" in item else item.get("value")))
    treat_as_percent = infer_percent_scale(weight for _, weight in rows)
    slices: list[AllocationSlice] = []
    for label, raw_weight in rows:
        weight = _as_weight(raw_weight, treat_as_percent=treat_as_percent)
        if weight is None:
            continue
        slices.append(AllocationSlice(label=label, weight=weight, source=source))
    slices.sort(key=lambda item: item.weight, reverse=True)
    return tuple(slices)


def normalize_holdings(
    etf_ticker: str,
    rows: Iterable[dict[str, Any]],
    *,
    source: str | None,
    as_of: str | None = None,
    sector_allocation: tuple[AllocationSlice, ...] = (),
    geographic_allocation: tuple[AllocationSlice, ...] = (),
    captured_at: str | None = None,
) -> EtfHoldingsSnapshot:
    material = [row for row in rows if isinstance(row, dict)]
    treat_as_percent = infer_percent_scale(
        row.get("weight") if "weight" in row else row.get("percent") if "percent" in row else row.get("holdingPercent")
        for row in material
    )
    holdings: list[EtfHolding] = []
    seen: set[str] = set()
    for row in material:
        name = optional_str(row.get("holding_name") or row.get("name") or row.get("company"))
        if name and name.upper() in NON_SECURITY_NAMES:
            continue
        ticker = normalize_ticker(row.get("holding_ticker") or row.get("ticker") or row.get("symbol") or row.get("cusip"))
        raw_weight = row.get("weight") if "weight" in row else row.get("percent") if "percent" in row else row.get("holdingPercent")
        weight = _as_weight(raw_weight, treat_as_percent=treat_as_percent)
        identity = ticker or name
        if identity is None:
            continue
        if identity in seen:
            continue
        seen.add(identity)
        holdings.append(
            EtfHolding(
                etf_ticker=etf_ticker.upper().strip(),
                holding_ticker=ticker,
                holding_name=name,
                weight=weight,
                shares=optional_float(row.get("shares") or row.get("share")),
                as_of=optional_str(row.get("as_of") or as_of),
                source=source,
            )
        )
    holdings.sort(key=lambda item: (item.weight is None, -(item.weight or 0.0), item.holding_ticker or "", item.holding_name or ""))
    return EtfHoldingsSnapshot(
        etf_ticker=etf_ticker.upper().strip(),
        captured_at=captured_at or utc_now_iso(),
        source=source,
        holdings=tuple(holdings),
        sector_allocation=sector_allocation,
        geographic_allocation=geographic_allocation,
    )


def unix_to_date(value: Any) -> str | None:
    number = optional_float(value)
    if number is None or number <= 0:
        return None
    try:
        return datetime.fromtimestamp(number, tz=UTC).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def profile_unavailable_fields(profile: EtfProfile) -> tuple[str, ...]:
    missing: list[str] = []
    for field_name in (
        "name",
        "issuer",
        "asset_class",
        "category",
        "description",
        "expense_ratio",
        "aum",
        "average_volume",
        "dividend_yield",
        "inception_date",
        "holdings_count",
    ):
        if getattr(profile, field_name) is None:
            missing.append(field_name)
    if not profile.geographic_exposure:
        missing.append("geographic_exposure")
    if not profile.sector_exposure:
        missing.append("sector_exposure")
    return tuple(missing)


def with_unavailable_fields(profile: EtfProfile) -> EtfProfile:
    return EtfProfile(
        ticker=profile.ticker,
        name=profile.name,
        issuer=profile.issuer,
        asset_class=profile.asset_class,
        category=profile.category,
        description=profile.description,
        expense_ratio=profile.expense_ratio,
        aum=profile.aum,
        average_volume=profile.average_volume,
        dividend_yield=profile.dividend_yield,
        inception_date=profile.inception_date,
        holdings_count=profile.holdings_count,
        geographic_exposure=profile.geographic_exposure,
        sector_exposure=profile.sector_exposure,
        source=profile.source,
        quote_type=profile.quote_type,
        updated_at=profile.updated_at,
        unavailable_fields=profile_unavailable_fields(profile),
    )


__all__ = [
    "infer_percent_scale",
    "normalize_allocation",
    "normalize_holdings",
    "normalize_ticker",
    "unix_to_date",
    "with_unavailable_fields",
]
