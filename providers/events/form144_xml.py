from __future__ import annotations

from datetime import datetime
from typing import Any
from xml.etree import ElementTree

from providers.events.form144_models import ProposedSaleNotice, normalize_cik, normalize_ticker


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find_text(element: ElementTree.Element, *local_names: str) -> str | None:
    wanted = {name.lower() for name in local_names}
    for descendant in element.iter():
        if _local_name(descendant.tag).lower() not in wanted:
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
    cleaned = value.replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _parse_xml_date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d-%b-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(text[:32], fmt).date().isoformat()
        except ValueError:
            continue
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def _sum_named_numbers(root: ElementTree.Element, *local_names: str) -> float | None:
    wanted = {name.lower() for name in local_names}
    total = 0.0
    found = False
    for descendant in root.iter():
        if _local_name(descendant.tag).lower() not in wanted:
            continue
        value = _parse_number((descendant.text or "").strip() or None)
        if value is None:
            continue
        total += value
        found = True
    return total if found else None


def _first_block(root: ElementTree.Element, *local_names: str) -> ElementTree.Element | None:
    wanted = {name.lower() for name in local_names}
    for descendant in root.iter():
        if _local_name(descendant.tag).lower() in wanted:
            return descendant
    return None


def _issuer_fields(root: ElementTree.Element) -> dict[str, Any]:
    block = _first_block(root, "issuerInfo", "issuerInformation", "issuer")
    if block is None:
        block = root
    return {
        "issuer_cik": normalize_cik(
            _find_text(block, "issuerCik", "cik") or _find_text(root, "issuerCik")
        ),
        "issuer_name": _find_text(block, "issuerName", "nameOfIssuer"),
        "ticker": normalize_ticker(
            _find_text(block, "issuerTradingSymbol", "tradingSymbol", "ticker")
        ),
    }


def _filer_fields(root: ElementTree.Element) -> dict[str, Any]:
    header = _first_block(root, "headerData", "filerInfo", "filer")
    if header is None:
        header = root
    form = _first_block(root, "formData", "issuerInfo", "issuerInformation")
    if form is None:
        form = root
    filer_cik = normalize_cik(
        _find_text(header, "cik", "filerCik", "rptOwnerCik")
        or _find_text(root, "filerCik", "rptOwnerCik")
    )
    issuer_cik = normalize_cik(_find_text(root, "issuerCik"))
    if filer_cik and issuer_cik and filer_cik == issuer_cik:
        header_only = _first_block(root, "headerData")
        if header_only is not None:
            filer_cik = normalize_cik(_find_text(header_only, "cik", "filerCik")) or filer_cik
    return {
        "filer_cik": filer_cik,
        "filer_name": _find_text(
            form,
            "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold",
            "rptOwnerName",
            "filerName",
        ),
        "relationship": _find_text(
            form,
            "relationshipToIssuer",
            "relationshipsToIssuer",
            "relationship",
        ),
    }


def parse_form144_xml(
    payload: bytes | str,
    *,
    accession_number: str,
    filed_at: str,
    fallback_ticker: str | None = None,
    fallback_issuer_cik: str | None = None,
) -> ProposedSaleNotice:
    root = ElementTree.fromstring(payload)
    issuer = _issuer_fields(root)
    filer = _filer_fields(root)
    securities = _first_block(root, "securitiesToBeSold", "securitiesInformation")
    if securities is None:
        securities = root
    proposed_units = _parse_number(
        _find_text(
            securities,
            "numberOfSharesOrUnitsToBeSold",
            "noOfSharesOrOtherUnitsToBeSold",
            "sharesToBeSold",
            "proposedShares",
        )
    )
    if proposed_units is None:
        proposed_units = _sum_named_numbers(
            root,
            "numberOfSharesOrUnitsToBeSold",
            "noOfSharesOrOtherUnitsToBeSold",
            "sharesToBeSold",
        )
    return ProposedSaleNotice(
        accession_number=accession_number,
        ticker=issuer["ticker"] or normalize_ticker(fallback_ticker),
        issuer_cik=issuer["issuer_cik"] or normalize_cik(fallback_issuer_cik),
        issuer_name=issuer["issuer_name"],
        filer_cik=filer["filer_cik"],
        filer_name=filer["filer_name"],
        relationship=filer["relationship"],
        filed_at=_parse_xml_date(filed_at) or filed_at[:10],
        approx_sale_date=_parse_xml_date(
            _find_text(securities, "approxDateOfSale", "approximateDateOfSale")
        ),
        proposed_units=proposed_units,
        aggregate_market_value=_parse_number(
            _find_text(securities, "aggregateMarketValue", "marketValue")
        ),
        broker=_find_text(securities, "name", "brokerName", "nameOfBroker"),
        prior_3m_units=_sum_named_numbers(
            root,
            "amountOfSecuritiesSold",
            "securitiesSoldDuringPast3Months",
            "numberOfSharesSold",
        ),
        prior_3m_proceeds=_sum_named_numbers(root, "grossProceeds", "groosProceeds"),
        securities_class=_find_text(
            securities,
            "securityClassTitle",
            "titleOfTheClassOfSecuritiesToBeSold",
            "nameOfSecurities",
        ),
        source="edgar_form144_xml",
    )


__all__ = ["parse_form144_xml"]
