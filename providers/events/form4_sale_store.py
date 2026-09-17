from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from config.form144 import (
    FORM4_KEEP_CANDIDATE_FILE,
    FORM4_SALE_ACQUIRED_DISPOSED,
    FORM4_SALE_CODES,
    FORM4_KEEP_SOURCE,
)
from providers.events.form144_models import Form4Sale, normalize_cik, normalize_ticker
from storage.cache.json_cache import load_json


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y"}


def form4_sale_from_keep_row(row: Mapping[str, Any]) -> Form4Sale | None:
    code = str(row.get("transaction_code") or row.get("transactionCode") or "").upper().strip()
    if code not in FORM4_SALE_CODES:
        return None
    acquired = str(
        row.get("acquired_disposed") or row.get("acquiredDisposed") or ""
    ).upper().strip()
    if acquired and acquired != FORM4_SALE_ACQUIRED_DISPOSED:
        return None
    if _as_bool(row.get("is_derivative") or row.get("isDerivative")):
        return None
    filed_at = str(row.get("filed_at") or row.get("filedAt") or "")[:10]
    transaction_date = str(
        row.get("transaction_date") or row.get("transactionDate") or filed_at
    )[:10]
    if not filed_at and not transaction_date:
        return None
    shares = row.get("shares")
    value = row.get("value_usd") if row.get("value_usd") is not None else row.get("valueUsd")
    try:
        share_value = None if shares is None else float(shares)
    except (TypeError, ValueError):
        share_value = None
    try:
        value_usd = None if value is None else float(value)
    except (TypeError, ValueError):
        value_usd = None
    return Form4Sale(
        accession_number=str(row.get("accession_number") or row.get("accessionNumber") or ""),
        ticker=normalize_ticker(str(row.get("ticker") or "") or None),
        issuer_cik=normalize_cik(str(row.get("issuer_cik") or row.get("issuerCik") or "") or None),
        filer_cik=normalize_cik(
            str(row.get("filer_cik") or row.get("owner_cik") or row.get("ownerCik") or "") or None
        ),
        filer_name=str(row.get("filer_name") or row.get("owner_name") or row.get("ownerName") or "")
        or None,
        filed_at=filed_at or transaction_date,
        transaction_date=transaction_date or filed_at,
        transaction_code=code,
        acquired_disposed=acquired or FORM4_SALE_ACQUIRED_DISPOSED,
        shares=share_value,
        value_usd=value_usd,
        source="section16_keep_json",
        is_derivative=False,
    )


def form4_sales_from_payload(payload: Any) -> list[Form4Sale]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("transactions") or payload.get("sales") or payload.get("form4_sales") or []
    else:
        rows = []
    sales: list[Form4Sale] = []
    if not isinstance(rows, list):
        return sales
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        parsed = form4_sale_from_keep_row(row)
        if parsed is not None:
            sales.append(parsed)
    return sales


def discover_form4_keep_store(
    path: Path | None = None,
) -> dict[str, Any]:
    """Locate the prior Section-16 KEEP Form 4 shadow store if present on disk.

    On main, live Form 4 events exist only inside `SecEventBundle` (short lookback,
    max three documents). The dedicated KEEP JSON lives on the isolated
    Section-16 branch at `data_store/section16_cache/open_market_transactions.json`.
    """

    candidate = path or FORM4_KEEP_CANDIDATE_FILE
    exists = candidate.exists()
    payload = load_json(candidate, {"transactions": []}) if exists else {"transactions": []}
    sales = form4_sales_from_payload(payload)
    return {
        "present": exists,
        "path": str(candidate),
        "source": FORM4_KEEP_SOURCE,
        "sale_count": len(sales),
        "sales": sales,
        "notes": (
            "Dedicated Form 4 KEEP JSON was found."
            if exists
            else (
                "No dedicated Form 4 KEEP store on this checkout. Live SEC overlay "
                "keeps only a short-lookback SecEventBundle. The Section-16 experiment "
                "branch writes open_market_transactions.json when present."
            )
        ),
    }


def merge_form4_sales(*groups: Sequence[Form4Sale]) -> list[Form4Sale]:
    merged: list[Form4Sale] = []
    seen: set[tuple[Any, ...]] = set()
    for group in groups:
        for row in group:
            key = (
                row.accession_number,
                row.filer_cik,
                row.transaction_date,
                row.transaction_code,
                row.shares,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


__all__ = [
    "discover_form4_keep_store",
    "form4_sale_from_keep_row",
    "form4_sales_from_payload",
    "merge_form4_sales",
]
