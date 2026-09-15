from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, Iterable, Sequence
from urllib.parse import urlencode

from config.sc13d import CONVERSION_REFERENCE_FORMS, PRIMARY_FORMS, SAMPLE_START, SEC_EFTS_SEARCH_URL
from config.settings import (
    SEC_EDGAR_BASE_URL,
    SEC_EDGAR_TIMEOUT_SECONDS,
    SEC_TICKER_MAP_URL,
    settings,
)
from providers.events.sc13d_models import Sc13dFiling, normalize_form, parse_iso_date
from providers.events.sc13d_parser import parse_sc13d_document
from providers.events.sec_edgar_client import _filing_url, _recent_filing_rows, _request_bytes, _request_json


_log = logging.getLogger(__name__)
_DISPLAY_NAME_RE = re.compile(
    r"(?P<name>.+?)\s+\((?P<ticker>[A-Z0-9.\-]{1,10})\)\s+\((?:CIK\s*)?(?P<cik>\d{1,10})\)",
    re.IGNORECASE,
)


def _normalize_cik(value: Any) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return str(int(str(value).strip())).zfill(10)
    except (TypeError, ValueError):
        digits = re.sub(r"\D", "", str(value))
        if not digits:
            return None
        return str(int(digits)).zfill(10)


class Sc13dEdgarClient:
    """Fetch SC 13D/A (and 13G conversion references) without touching live SEC scoring."""

    def __init__(
        self,
        *,
        user_agent: str | None = None,
        timeout_seconds: int = SEC_EDGAR_TIMEOUT_SECONDS,
    ) -> None:
        self.user_agent = (user_agent or settings.sec_edgar_user_agent).strip()
        self.timeout_seconds = timeout_seconds

    @property
    def enabled(self) -> bool:
        return bool(self.user_agent)

    def ticker_map(self) -> dict[str, str]:
        payload = _request_json(
            SEC_TICKER_MAP_URL,
            user_agent=self.user_agent,
            timeout_seconds=self.timeout_seconds,
        )
        mapping: dict[str, str] = {}
        rows = payload.values() if isinstance(payload, dict) else payload
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            ticker = str(row.get("ticker") or "").upper().strip()
            cik = _normalize_cik(row.get("cik_str"))
            if ticker and cik:
                mapping[ticker] = cik
        return mapping

    def ingest_ticker_submissions(
        self,
        tickers: Sequence[str],
        *,
        since: date = SAMPLE_START,
        fetch_documents: bool = True,
        include_13g: bool = True,
    ) -> dict[str, list[Sc13dFiling]]:
        mapping = self.ticker_map()
        thirteen_d: list[Sc13dFiling] = []
        thirteen_g: list[Sc13dFiling] = []
        for ticker in tickers:
            normalized = ticker.upper().strip()
            cik = mapping.get(normalized)
            if cik is None:
                continue
            try:
                submissions = _request_json(
                    f"{SEC_EDGAR_BASE_URL}/submissions/CIK{cik}.json",
                    user_agent=self.user_agent,
                    timeout_seconds=self.timeout_seconds,
                )
            except Exception:
                _log.info("SC 13D submissions lookup failed for %s.", normalized, exc_info=True)
                continue
            issuer_name = str((submissions or {}).get("name") or "") if isinstance(submissions, dict) else ""
            rows = _recent_filing_rows(submissions if isinstance(submissions, dict) else {})
            for row in rows:
                form = normalize_form(str(row.get("form") or ""))
                filed = parse_iso_date(str(row.get("filingDate") or ""))
                if form is None or filed is None or filed < since:
                    continue
                accession = str(row.get("accessionNumber") or "")
                primary_document = str(row.get("primaryDocument") or "")
                url = _filing_url(cik, accession, primary_document)
                parsed = parse_sc13d_document(self._document_bytes(url) if fetch_documents else "")
                filing = Sc13dFiling(
                    accession_number=accession,
                    form=form,
                    filed_at=filed.isoformat(),
                    ticker=normalized,
                    issuer_cik=cik,
                    issuer_name=parsed.issuer_name or issuer_name or None,
                    reporting_cik=parsed.reporting_cik,
                    reporting_name=parsed.reporting_name,
                    url=url,
                    purpose_text=parsed.purpose_text,
                    percent_of_class=parsed.percent_of_class,
                    conversion_text_flag=parsed.conversion_text_flag,
                    source="sec_submissions",
                    raw_excerpt=parsed.purpose_text[:1500],
                )
                if form in PRIMARY_FORMS:
                    thirteen_d.append(filing)
                elif include_13g and form in CONVERSION_REFERENCE_FORMS:
                    thirteen_g.append(filing)
        return {"sc13d": thirteen_d, "sc13g": thirteen_g}

    def ingest_efts_search(
        self,
        *,
        since: date = SAMPLE_START,
        until: date | None = None,
        forms: Sequence[str] = ("SC 13D", "SC 13D/A"),
        max_hits: int = 200,
        fetch_documents: bool = True,
    ) -> list[Sc13dFiling]:
        if not self.enabled:
            return []
        end = until or date.today()
        query = {
            "q": "*",
            "forms": ",".join(forms),
            "dateRange": "custom",
            "startdt": since.isoformat(),
            "enddt": end.isoformat(),
        }
        url = f"{SEC_EFTS_SEARCH_URL}?{urlencode(query)}"
        try:
            payload = _request_json(url, user_agent=self.user_agent, timeout_seconds=self.timeout_seconds)
        except Exception:
            _log.info("SC 13D EFTS search failed.", exc_info=True)
            return []
        hits = (((payload or {}).get("hits") or {}).get("hits") or []) if isinstance(payload, dict) else []
        filings: list[Sc13dFiling] = []
        for hit in hits[:max_hits]:
            if not isinstance(hit, dict):
                continue
            source = hit.get("_source") if isinstance(hit.get("_source"), dict) else {}
            hit_id = str(hit.get("_id") or "")
            accession, _, filename = hit_id.partition(":")
            display_names = source.get("display_names") or []
            ticker, issuer_cik, issuer_name = _parse_display_name(
                display_names[0] if display_names else ""
            )
            form = normalize_form(
                (source.get("form_type") or [None])[0]
                if isinstance(source.get("form_type"), list)
                else source.get("file_type")
            )
            filed = parse_iso_date(str(source.get("file_date") or source.get("period_ending") or ""))
            if form is None or filed is None or not ticker or not issuer_cik:
                continue
            document_url = _filing_url(issuer_cik, accession, filename)
            parsed = parse_sc13d_document(self._document_bytes(document_url) if fetch_documents else "")
            filings.append(
                Sc13dFiling(
                    accession_number=accession,
                    form=form,
                    filed_at=filed.isoformat(),
                    ticker=ticker,
                    issuer_cik=issuer_cik,
                    issuer_name=parsed.issuer_name or issuer_name,
                    reporting_cik=parsed.reporting_cik,
                    reporting_name=parsed.reporting_name,
                    url=document_url,
                    purpose_text=parsed.purpose_text,
                    percent_of_class=parsed.percent_of_class,
                    conversion_text_flag=parsed.conversion_text_flag,
                    source="sec_efts",
                    raw_excerpt=parsed.purpose_text[:1500],
                )
            )
        return filings

    def _document_bytes(self, url: str) -> bytes:
        try:
            return _request_bytes(
                url,
                user_agent=self.user_agent,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception:
            _log.info("Could not fetch SC 13D document %s.", url, exc_info=True)
            return b""


def filings_from_records(records: Iterable[dict[str, Any]]) -> list[Sc13dFiling]:
    filings: list[Sc13dFiling] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        if "purpose_text" not in row and "raw_text" in row:
            parsed = parse_sc13d_document(str(row.get("raw_text") or ""))
            row = {
                **row,
                "purpose_text": parsed.purpose_text,
                "percent_of_class": row.get("percent_of_class", parsed.percent_of_class),
                "reporting_cik": row.get("reporting_cik") or parsed.reporting_cik,
                "reporting_name": row.get("reporting_name") or parsed.reporting_name,
                "issuer_name": row.get("issuer_name") or parsed.issuer_name,
                "conversion_text_flag": bool(row.get("conversion_text_flag") or parsed.conversion_text_flag),
                "raw_excerpt": parsed.purpose_text[:1500],
            }
        try:
            form = normalize_form(str(row.get("form") or "SC 13D")) or "SC 13D"
            filings.append(
                Sc13dFiling.from_dict(
                    {
                        "accession_number": str(row.get("accession_number") or ""),
                        "form": form,
                        "filed_at": str(row.get("filed_at") or row.get("filingDate") or ""),
                        "ticker": str(row.get("ticker") or "").upper().strip(),
                        "issuer_cik": _normalize_cik(row.get("issuer_cik")),
                        "issuer_name": row.get("issuer_name"),
                        "reporting_cik": _normalize_cik(row.get("reporting_cik")),
                        "reporting_name": row.get("reporting_name"),
                        "url": str(row.get("url") or ""),
                        "purpose_text": str(row.get("purpose_text") or ""),
                        "percent_of_class": row.get("percent_of_class"),
                        "prior_percent_of_class": row.get("prior_percent_of_class"),
                        "conversion_text_flag": bool(row.get("conversion_text_flag")),
                        "conversion_prior_13g": bool(row.get("conversion_prior_13g")),
                        "source": str(row.get("source") or "corpus"),
                        "raw_excerpt": str(row.get("raw_excerpt") or "")[:1500],
                    }
                )
            )
        except (TypeError, ValueError):
            continue
    return filings


def load_corpus_file(path) -> list[Sc13dFiling]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        payload = json.loads(text)
        if isinstance(payload, dict):
            records = payload.get("filings") or payload.get("sc13d") or []
        else:
            records = payload
    return filings_from_records(records if isinstance(records, list) else [])


def _parse_display_name(value: Any) -> tuple[str | None, str | None, str | None]:
    text = str(value or "").strip()
    match = _DISPLAY_NAME_RE.search(text)
    if not match:
        return None, None, text or None
    return (
        match.group("ticker").upper(),
        _normalize_cik(match.group("cik")),
        match.group("name").strip(),
    )


def build_sc13d_edgar_client() -> Sc13dEdgarClient:
    return Sc13dEdgarClient()


__all__ = [
    "Sc13dEdgarClient",
    "build_sc13d_edgar_client",
    "filings_from_records",
    "load_corpus_file",
]
