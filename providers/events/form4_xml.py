from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from providers.events.section16_codes import (
    footnote_indicates_10b5_1,
    is_open_market_code,
    normalize_transaction_code,
    truthy_flag,
)
from providers.events.section16_models import InsiderTransaction


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(element: ElementTree.Element, local_name: str) -> str | None:
    for descendant in element.iter():
        if _local_name(descendant.tag) != local_name:
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


def _collect_footnotes(root: ElementTree.Element) -> dict[str, str]:
    footnotes: dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "footnote":
            continue
        footnote_id = (
            element.attrib.get("id")
            or element.attrib.get("{http://www.w3.org/1999/xlink}label")
            or _find_text(element, "id")
            or ""
        ).strip()
        text = " ".join(part.strip() for part in element.itertext() if part.strip())
        if footnote_id:
            footnotes[footnote_id] = text
        elif text:
            footnotes[f"anon-{len(footnotes)+1}"] = text
    return footnotes


def _owner_block(root: ElementTree.Element) -> dict[str, Any]:
    owner: dict[str, Any] = {
        "owner_cik": None,
        "owner_name": None,
        "owner_title": None,
        "is_director": False,
        "is_officer": False,
        "is_ten_percent_owner": False,
    }
    for element in root.iter():
        if _local_name(element.tag) != "reportingOwner":
            continue
        owner["owner_cik"] = _find_text(element, "rptOwnerCik")
        owner["owner_name"] = _find_text(element, "rptOwnerName")
        owner["owner_title"] = _find_text(element, "officerTitle")
        owner["is_director"] = truthy_flag(_find_text(element, "isDirector"))
        owner["is_officer"] = truthy_flag(_find_text(element, "isOfficer"))
        owner["is_ten_percent_owner"] = truthy_flag(_find_text(element, "isTenPercentOwner"))
        break
    return owner


def _issuer_block(root: ElementTree.Element) -> tuple[str | None, str | None, str | None]:
    for element in root.iter():
        if _local_name(element.tag) != "issuer":
            continue
        return (
            _find_text(element, "issuerCik"),
            _find_text(element, "issuerName"),
            (_find_text(element, "issuerTradingSymbol") or "").upper().strip() or None,
        )
    return None, None, None


def _footnote_ids_for(element: ElementTree.Element) -> tuple[str, ...]:
    ids: list[str] = []
    for descendant in element.iter():
        if _local_name(descendant.tag) != "footnoteId":
            continue
        footnote_id = (descendant.attrib.get("id") or (descendant.text or "")).strip()
        if footnote_id:
            ids.append(footnote_id)
    return tuple(dict.fromkeys(ids))


def _transaction_is_10b5_1(
    transaction: ElementTree.Element,
    footnotes: dict[str, str],
    footnote_ids: tuple[str, ...],
    *,
    document_10b5_1: bool,
) -> bool:
    if document_10b5_1:
        return True
    footnote_texts = [footnotes.get(footnote_id, "") for footnote_id in footnote_ids]
    if footnote_indicates_10b5_1(*footnote_texts, _find_text(transaction, "footnote")):
        return True
    for local_name in (
        "is10b51Transaction",
        "tenb51",
        "affirmativeDefense",
        "goodFaithDetermination",
    ):
        if truthy_flag(_find_text(transaction, local_name)):
            return True
    return False


def parse_form4_xml(
    payload: bytes | str,
    *,
    accession_number: str,
    filed_at: str,
    fallback_ticker: str | None = None,
    fallback_issuer_cik: str | None = None,
) -> list[InsiderTransaction]:
    root = ElementTree.fromstring(payload)
    footnotes = _collect_footnotes(root)
    owner = _owner_block(root)
    issuer_cik, issuer_name, ticker = _issuer_block(root)
    ticker = ticker or (fallback_ticker or "").upper().strip() or ""
    issuer_cik = issuer_cik or fallback_issuer_cik
    document_10b5_1 = truthy_flag(_find_text(root, "aff10b5One")) or truthy_flag(
        _find_text(root, "AFF10B5ONE")
    )

    rows: list[InsiderTransaction] = []
    for transaction in root.iter():
        local = _local_name(transaction.tag)
        if local not in {"nonDerivativeTransaction", "derivativeTransaction"}:
            continue
        code = normalize_transaction_code(_find_text(transaction, "transactionCode"))
        if not is_open_market_code(code):
            continue
        shares = _parse_number(_find_text(transaction, "transactionShares"))
        price = _parse_number(_find_text(transaction, "transactionPricePerShare"))
        value = None if shares is None or price is None else shares * price
        footnote_ids = _footnote_ids_for(transaction)
        is_10b5_1 = _transaction_is_10b5_1(
            transaction,
            footnotes,
            footnote_ids,
            document_10b5_1=document_10b5_1,
        )
        rows.append(
            InsiderTransaction(
                accession_number=accession_number,
                ticker=ticker,
                issuer_cik=issuer_cik,
                issuer_name=issuer_name,
                owner_cik=owner["owner_cik"],
                owner_name=owner["owner_name"],
                owner_title=owner["owner_title"],
                is_director=bool(owner["is_director"]),
                is_officer=bool(owner["is_officer"]),
                is_ten_percent_owner=bool(owner["is_ten_percent_owner"]),
                transaction_date=_parse_xml_date(_find_text(transaction, "transactionDate")) or filed_at[:10],
                filed_at=filed_at[:10],
                transaction_code=code,
                acquired_disposed=(_find_text(transaction, "transactionAcquiredDisposedCode") or "").upper() or None,
                shares=shares,
                price_per_share=price,
                value_usd=value,
                is_10b5_1=is_10b5_1,
                is_derivative=local == "derivativeTransaction",
                source="edgar_form4_xml",
                footnote_ids=footnote_ids,
                document_type="4",
            )
        )
    return rows


def classify_form4_from_transactions(
    transactions: list[InsiderTransaction],
) -> tuple[str, int, int, str, float | None]:
    """Preserve the live SEC event classifier: P/A purchases and S/D sales only."""
    purchases = [
        row
        for row in transactions
        if not row.is_derivative
        and row.transaction_code == "P"
        and row.acquired_disposed == "A"
    ]
    sales = [
        row
        for row in transactions
        if not row.is_derivative
        and row.transaction_code == "S"
        and row.acquired_disposed == "D"
    ]
    purchase_value = sum(float(row.value_usd or 0.0) for row in purchases)
    sale_value = sum(float(row.value_usd or 0.0) for row in sales)
    if purchases and not sales:
        importance = 3 if purchase_value >= 250_000 else 2
        summary = (
            f"An insider purchase was disclosed ({len(purchases)} open-market "
            f"transaction{'s' if len(purchases) != 1 else ''})."
        )
        return "insider_purchase", 1, importance, summary, purchase_value or None
    if sales and not purchases:
        summary = (
            f"An insider sale was disclosed ({len(sales)} open-market "
            f"transaction{'s' if len(sales) != 1 else ''})."
        )
        return "insider_sale", -1, 1, summary, sale_value or None
    if purchases and sales:
        return (
            "insider_mixed",
            0,
            1,
            "Mixed open-market insider transactions were disclosed.",
            (purchase_value + sale_value) or None,
        )
    return (
        "insider_disclosure",
        0,
        1,
        "An ownership disclosure was filed; no open-market purchase or sale was identified.",
        None,
    )


__all__ = ["classify_form4_from_transactions", "parse_form4_xml"]
