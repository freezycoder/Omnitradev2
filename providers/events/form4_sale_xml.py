from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from config.form144 import FORM4_SALE_ACQUIRED_DISPOSED, FORM4_SALE_CODES
from providers.events.form144_models import Form4Sale, normalize_cik, normalize_ticker


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(element: ElementTree.Element, local_name: str) -> str | None:
    wanted = local_name.lower()
    for descendant in element.iter():
        if _local_name(descendant.tag).lower() != wanted:
            continue
        text = (descendant.text or "").strip()
        if text:
            return text
        for nested in descendant.iter():
            if nested is descendant:
                continue
            nested_text = (nested.text or "").strip()
            if nested_text:
                return nested_text
    return None


def _parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_xml_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text[:32], fmt).date().isoformat()
        except ValueError:
            continue
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def parse_form4_sale_xml(
    payload: bytes | str,
    *,
    accession_number: str,
    filed_at: str,
    fallback_ticker: str | None = None,
    fallback_issuer_cik: str | None = None,
) -> list[Form4Sale]:
    """Extract open-market Form 4 sales (code S / disposed) for 144 matching.

    This is a matching adapter, not the live SEC event classifier.
    """

    root = ElementTree.fromstring(payload)
    owner_cik = normalize_cik(_find_text(root, "rptOwnerCik"))
    owner_name = _find_text(root, "rptOwnerName")
    issuer_cik = normalize_cik(_find_text(root, "issuerCik")) or normalize_cik(
        fallback_issuer_cik
    )
    ticker = normalize_ticker(_find_text(root, "issuerTradingSymbol")) or normalize_ticker(
        fallback_ticker
    )
    rows: list[Form4Sale] = []
    for transaction in root.iter():
        local = _local_name(transaction.tag)
        if local not in {"nonDerivativeTransaction", "derivativeTransaction"}:
            continue
        code = (_find_text(transaction, "transactionCode") or "").upper().strip()
        acquired_disposed = (
            _find_text(transaction, "transactionAcquiredDisposedCode") or ""
        ).upper().strip()
        if code not in FORM4_SALE_CODES:
            continue
        if acquired_disposed and acquired_disposed != FORM4_SALE_ACQUIRED_DISPOSED:
            continue
        shares = _parse_number(_find_text(transaction, "transactionShares"))
        price = _parse_number(_find_text(transaction, "transactionPricePerShare"))
        value = None if shares is None or price is None else shares * price
        rows.append(
            Form4Sale(
                accession_number=accession_number,
                ticker=ticker,
                issuer_cik=issuer_cik,
                filer_cik=owner_cik,
                filer_name=owner_name,
                filed_at=_parse_xml_date(filed_at) or filed_at[:10],
                transaction_date=_parse_xml_date(_find_text(transaction, "transactionDate"))
                or filed_at[:10],
                transaction_code=code,
                acquired_disposed=acquired_disposed or FORM4_SALE_ACQUIRED_DISPOSED,
                shares=shares,
                value_usd=value,
                source="edgar_form4_xml",
                is_derivative=local == "derivativeTransaction",
            )
        )
    return [row for row in rows if not row.is_derivative]


__all__ = ["parse_form4_sale_xml"]
