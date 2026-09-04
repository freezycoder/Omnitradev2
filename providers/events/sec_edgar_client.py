from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from threading import RLock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from config.settings import (
    SEC_ARCHIVES_BASE_URL,
    SEC_CACHE_TTL_SECONDS,
    SEC_EDGAR_BASE_URL,
    SEC_EDGAR_TIMEOUT_SECONDS,
    SEC_EVENT_LOOKBACK_DAYS,
    SEC_MAX_EVENTS,
    SEC_MAX_FORM4_DOCUMENTS,
    SEC_TICKER_MAP_URL,
    settings,
)


_log = logging.getLogger(__name__)
_CACHE_LOCK = RLock()
_REQUEST_LOCK = RLock()
_REQUEST_CACHE: dict[str, tuple[float, bytes]] = {}
_REQUEST_ERROR_CACHE: dict[str, tuple[float, int]] = {}
_LAST_REQUEST_AT = 0.0
_MIN_REQUEST_INTERVAL_SECONDS = 0.12


@dataclass(frozen=True)
class SecFilingEvent:
    form: str
    filed_at: str
    category: str
    direction: int
    importance: int
    summary: str
    url: str
    accession_number: str
    items: list[str] = field(default_factory=list)
    transaction_value: float | None = None


@dataclass(frozen=True)
class SecEventBundle:
    ticker: str
    cik: str | None
    status: str
    retrieved_at: str
    events: list[SecFilingEvent] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_EIGHT_K_ITEMS: dict[str, tuple[str, int, int, str]] = {
    "1.01": ("material_agreement", 0, 2, "A material agreement was reported; direction depends on the filing details."),
    "1.02": ("agreement_termination", -1, 3, "A material agreement was terminated."),
    "2.01": ("acquisition_or_disposition", 0, 2, "An acquisition or asset disposition was reported; direction is not inferred from the form alone."),
    "2.02": ("earnings_update", 0, 2, "Results of operations or financial condition were reported."),
    "2.05": ("restructuring", -1, 2, "Exit or disposal costs were reported."),
    "2.06": ("impairment", -1, 4, "A material impairment was reported."),
    "3.01": ("listing_risk", -1, 4, "A listing-standard or delisting notice was reported."),
    "5.02": ("leadership_change", 0, 2, "A director or executive change was reported; direction is not inferred from the form alone."),
    "7.01": ("regulation_fd", 0, 1, "A Regulation FD disclosure was reported."),
    "8.01": ("other_material_event", 0, 1, "Another material company event was reported."),
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _request_bytes(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    cache_ttl_seconds: int = SEC_CACHE_TTL_SECONDS,
) -> bytes:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _REQUEST_CACHE.get(url)
        if cached and now - cached[0] <= cache_ttl_seconds:
            return cached[1]
        cached_error = _REQUEST_ERROR_CACHE.get(url)
        if cached_error and now - cached_error[0] <= 60:
            raise HTTPError(url, cached_error[1], "Cached SEC HTTP error", None, None)

    global _LAST_REQUEST_AT
    with _REQUEST_LOCK:
        with _CACHE_LOCK:
            cached = _REQUEST_CACHE.get(url)
            if cached and time.monotonic() - cached[0] <= cache_ttl_seconds:
                return cached[1]
            cached_error = _REQUEST_ERROR_CACHE.get(url)
            if cached_error and time.monotonic() - cached_error[0] <= 60:
                raise HTTPError(url, cached_error[1], "Cached SEC HTTP error", None, None)
        wait_seconds = _MIN_REQUEST_INTERVAL_SECONDS - (time.monotonic() - _LAST_REQUEST_AT)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        request = Request(
            url,
            headers={
                "Accept": "application/json, application/xml, text/xml, */*",
                "User-Agent": user_agent,
            },
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                payload = response.read()
        except HTTPError as exc:
            with _CACHE_LOCK:
                _REQUEST_ERROR_CACHE[url] = (time.monotonic(), exc.code)
            raise
        finally:
            _LAST_REQUEST_AT = time.monotonic()

    with _CACHE_LOCK:
        _REQUEST_CACHE[url] = (time.monotonic(), payload)
    return payload


def _request_json(url: str, *, user_agent: str, timeout_seconds: int) -> Any:
    return json.loads(
        _request_bytes(
            url,
            user_agent=user_agent,
            timeout_seconds=timeout_seconds,
        ).decode("utf-8")
    )


def _filing_url(cik: str, accession: str, primary_document: str) -> str:
    accession_path = accession.replace("-", "")
    return f"{SEC_ARCHIVES_BASE_URL}/{int(cik)}/{accession_path}/{primary_document}"


def _normalize_items(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _recent_filing_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict):
        return []
    field_names = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "form",
        "primaryDocument",
        "items",
    )
    lengths = [len(recent.get(field, [])) for field in field_names if isinstance(recent.get(field), list)]
    row_count = max(lengths, default=0)
    rows: list[dict[str, Any]] = []
    for index in range(row_count):
        row: dict[str, Any] = {}
        for field_name in field_names:
            values = recent.get(field_name, [])
            row[field_name] = values[index] if isinstance(values, list) and index < len(values) else None
        rows.append(row)
    return rows


def _classify_eight_k(row: dict[str, Any], cik: str) -> SecFilingEvent:
    items = _normalize_items(row.get("items"))
    classifications = [_EIGHT_K_ITEMS[item] for item in items if item in _EIGHT_K_ITEMS]
    if classifications:
        category, direction, importance, _ = max(
            classifications,
            key=lambda item: (abs(item[1] * item[2]), item[2]),
        )
        summaries = [item[3] for item in classifications]
        summary = " ".join(dict.fromkeys(summaries))
    else:
        category, direction, importance = "material_filing", 0, 1
        summary = "A material current report was filed."

    accession = str(row.get("accessionNumber") or "")
    primary_document = str(row.get("primaryDocument") or "")
    return SecFilingEvent(
        form=str(row.get("form") or "8-K"),
        filed_at=str(row.get("filingDate") or ""),
        category=category,
        direction=direction,
        importance=importance,
        summary=summary,
        url=_filing_url(cik, accession, primary_document),
        accession_number=accession,
        items=items,
    )


def _find_text(element: ElementTree.Element, local_name: str) -> str | None:
    for descendant in element.iter():
        if descendant.tag.rsplit("}", 1)[-1] != local_name:
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
        return float(value.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _classify_form4(
    row: dict[str, Any],
    cik: str,
    *,
    user_agent: str,
    timeout_seconds: int,
) -> SecFilingEvent:
    accession = str(row.get("accessionNumber") or "")
    primary_document = str(row.get("primaryDocument") or "")
    filing_url = _filing_url(cik, accession, primary_document)
    purchases = 0
    sales = 0
    purchase_value = 0.0
    sale_value = 0.0
    try:
        root = ElementTree.fromstring(
            _request_bytes(
                filing_url,
                user_agent=user_agent,
                timeout_seconds=timeout_seconds,
            )
        )
        for transaction in root.iter():
            if transaction.tag.rsplit("}", 1)[-1] != "nonDerivativeTransaction":
                continue
            code = (_find_text(transaction, "transactionCode") or "").upper()
            acquired_disposed = (_find_text(transaction, "transactionAcquiredDisposedCode") or "").upper()
            shares = _parse_number(_find_text(transaction, "transactionShares"))
            price = _parse_number(_find_text(transaction, "transactionPricePerShare"))
            value = (shares or 0.0) * (price or 0.0)
            if code == "P" and acquired_disposed == "A":
                purchases += 1
                purchase_value += value
            elif code == "S" and acquired_disposed == "D":
                sales += 1
                sale_value += value
    except (ElementTree.ParseError, HTTPError, URLError, TimeoutError, ValueError):
        _log.info("Could not classify Form 4 transaction details for %s.", accession, exc_info=True)

    if purchases and not sales:
        direction = 1
        importance = 3 if purchase_value >= 250_000 else 2
        summary = f"An insider purchase was disclosed ({purchases} open-market transaction{'s' if purchases != 1 else ''})."
        category = "insider_purchase"
        transaction_value = purchase_value or None
    elif sales and not purchases:
        direction = -1
        importance = 1
        summary = f"An insider sale was disclosed ({sales} open-market transaction{'s' if sales != 1 else ''})."
        category = "insider_sale"
        transaction_value = sale_value or None
    elif purchases and sales:
        direction = 0
        importance = 1
        summary = "Mixed open-market insider transactions were disclosed."
        category = "insider_mixed"
        transaction_value = (purchase_value + sale_value) or None
    else:
        direction = 0
        importance = 1
        summary = "An ownership disclosure was filed; no open-market purchase or sale was identified."
        category = "insider_disclosure"
        transaction_value = None

    return SecFilingEvent(
        form="4",
        filed_at=str(row.get("filingDate") or ""),
        category=category,
        direction=direction,
        importance=importance,
        summary=summary,
        url=filing_url,
        accession_number=accession,
        transaction_value=transaction_value,
    )


class SecEdgarClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: int = SEC_EDGAR_TIMEOUT_SECONDS,
    ) -> None:
        self.user_agent = user_agent.strip()
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.user_agent)

    def _ticker_to_cik(self, ticker: str) -> str | None:
        payload = _request_json(
            SEC_TICKER_MAP_URL,
            user_agent=self.user_agent,
            timeout_seconds=self.timeout_seconds,
        )
        normalized = ticker.upper().strip()
        rows = payload.values() if isinstance(payload, dict) else payload
        for row in rows or []:
            if not isinstance(row, dict) or str(row.get("ticker") or "").upper().strip() != normalized:
                continue
            cik = row.get("cik_str")
            if cik is not None:
                return str(int(cik)).zfill(10)
        return None

    def get_company_events(
        self,
        ticker: str,
        *,
        lookback_days: int = SEC_EVENT_LOOKBACK_DAYS,
    ) -> SecEventBundle:
        normalized = ticker.upper().strip()
        retrieved_at = _now_iso()
        if not self.enabled:
            return SecEventBundle(
                ticker=normalized,
                cik=None,
                status="unavailable",
                retrieved_at=retrieved_at,
                message="SEC EDGAR is disabled because its declared User-Agent is missing.",
            )
        try:
            cik = self._ticker_to_cik(normalized)
            if cik is None:
                return SecEventBundle(
                    ticker=normalized,
                    cik=None,
                    status="not_applicable",
                    retrieved_at=retrieved_at,
                    message="No SEC CIK mapping was found for this ticker.",
                )
            submissions = _request_json(
                f"{SEC_EDGAR_BASE_URL}/submissions/CIK{cik}.json",
                user_agent=self.user_agent,
                timeout_seconds=self.timeout_seconds,
            )
        except HTTPError as exc:
            if exc.code == 429:
                message = "SEC EDGAR rate limit reached."
            elif exc.code == 403:
                message = "SEC EDGAR denied automated access; verify the declared User-Agent contact or retry later."
            else:
                message = f"SEC EDGAR HTTP {exc.code}."
            return SecEventBundle(normalized, None, "unavailable", retrieved_at, message=message)
        except (URLError, TimeoutError, json.JSONDecodeError, ValueError):
            _log.warning("SEC EDGAR request failed for %s.", normalized, exc_info=True)
            return SecEventBundle(
                normalized,
                None,
                "unavailable",
                retrieved_at,
                message="SEC EDGAR is unavailable right now.",
            )

        cutoff = date.today() - timedelta(days=max(lookback_days, 1))
        rows = [
            row
            for row in _recent_filing_rows(submissions if isinstance(submissions, dict) else {})
            if str(row.get("filingDate") or "") >= cutoff.isoformat()
        ]
        events: list[SecFilingEvent] = []
        form4_rows: list[dict[str, Any]] = []
        for row in rows:
            form = str(row.get("form") or "").upper()
            if form in {"8-K", "8-K/A"}:
                events.append(_classify_eight_k(row, cik))
            elif form in {"6-K", "6-K/A"}:
                accession = str(row.get("accessionNumber") or "")
                primary_document = str(row.get("primaryDocument") or "")
                events.append(
                    SecFilingEvent(
                        form=form,
                        filed_at=str(row.get("filingDate") or ""),
                        category="foreign_issuer_update",
                        direction=0,
                        importance=1,
                        summary="A foreign-issuer current report was filed.",
                        url=_filing_url(cik, accession, primary_document),
                        accession_number=accession,
                    )
                )
            elif form == "424B5":
                accession = str(row.get("accessionNumber") or "")
                primary_document = str(row.get("primaryDocument") or "")
                events.append(
                    SecFilingEvent(
                        form=form,
                        filed_at=str(row.get("filingDate") or ""),
                        category="securities_offering",
                        direction=-1,
                        importance=3,
                        summary="A securities offering prospectus was filed.",
                        url=_filing_url(cik, accession, primary_document),
                        accession_number=accession,
                    )
                )
            elif form in {"S-3", "F-3"}:
                accession = str(row.get("accessionNumber") or "")
                primary_document = str(row.get("primaryDocument") or "")
                events.append(
                    SecFilingEvent(
                        form=form,
                        filed_at=str(row.get("filingDate") or ""),
                        category="shelf_registration",
                        direction=-1,
                        importance=1,
                        summary="A shelf registration was filed; this is potential rather than confirmed dilution.",
                        url=_filing_url(cik, accession, primary_document),
                        accession_number=accession,
                    )
                )
            elif form in {"4", "4/A"} and len(form4_rows) < SEC_MAX_FORM4_DOCUMENTS:
                form4_rows.append(row)

        for row in form4_rows:
            events.append(
                _classify_form4(
                    row,
                    cik,
                    user_agent=self.user_agent,
                    timeout_seconds=self.timeout_seconds,
                )
            )

        purchase_count = sum(event.category == "insider_purchase" for event in events)
        sale_count = sum(event.category == "insider_sale" for event in events)
        if purchase_count >= 2:
            events.append(
                SecFilingEvent(
                    form="4 cluster",
                    filed_at=max(event.filed_at for event in events if event.category == "insider_purchase"),
                    category="insider_purchase_cluster",
                    direction=1,
                    importance=3,
                    summary=f"{purchase_count} recent Form 4 filings contained open-market insider purchases.",
                    url=f"https://www.sec.gov/edgar/browse/?CIK={int(cik)}",
                    accession_number="cluster",
                )
            )
        elif sale_count >= 3:
            events.append(
                SecFilingEvent(
                    form="4 cluster",
                    filed_at=max(event.filed_at for event in events if event.category == "insider_sale"),
                    category="insider_sale_cluster",
                    direction=-1,
                    importance=2,
                    summary=f"{sale_count} recent Form 4 filings contained open-market insider sales.",
                    url=f"https://www.sec.gov/edgar/browse/?CIK={int(cik)}",
                    accession_number="cluster",
                )
            )

        events.sort(key=lambda event: event.filed_at, reverse=True)
        return SecEventBundle(
            ticker=normalized,
            cik=cik,
            status="available",
            retrieved_at=retrieved_at,
            events=events[:SEC_MAX_EVENTS],
            message=None if events else "No material or ownership filings were found in the lookback window.",
        )


def build_sec_edgar_client() -> SecEdgarClient:
    return SecEdgarClient(user_agent=settings.sec_edgar_user_agent)


def sec_event_bundle_from_dict(payload: dict[str, Any] | None) -> SecEventBundle | None:
    if not payload:
        return None
    events = [
        SecFilingEvent(**event)
        for event in payload.get("events", [])
        if isinstance(event, dict)
    ]
    return SecEventBundle(
        ticker=str(payload.get("ticker") or ""),
        cik=str(payload["cik"]) if payload.get("cik") is not None else None,
        status=str(payload.get("status") or "unavailable"),
        retrieved_at=str(payload.get("retrieved_at") or _now_iso()),
        events=events,
        message=str(payload["message"]) if payload.get("message") else None,
    )


__all__ = [
    "SecEdgarClient",
    "SecEventBundle",
    "SecFilingEvent",
    "build_sec_edgar_client",
    "sec_event_bundle_from_dict",
]
