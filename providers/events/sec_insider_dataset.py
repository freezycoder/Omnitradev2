from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from config.section16 import SEC_INSIDER_ZIP_URL_TEMPLATE
from providers.events.section16_codes import (
    footnote_indicates_10b5_1,
    is_open_market_code,
    normalize_transaction_code,
    truthy_flag,
)
from providers.events.section16_models import InsiderTransaction


_log = logging.getLogger(__name__)

REQUIRED_TABLES = ("SUBMISSION", "REPORTINGOWNER", "NONDERIV_TRANS")
OPTIONAL_TABLES = ("FOOTNOTES",)

_SEC_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%B-%Y")


def quarterly_zip_url(year: int, quarter: int) -> str:
    if quarter not in {1, 2, 3, 4}:
        raise ValueError(f"Quarter must be 1-4, received {quarter}.")
    return SEC_INSIDER_ZIP_URL_TEMPLATE.format(year=int(year), quarter=int(quarter))


def _normalize_header(name: str) -> str:
    return str(name or "").strip().upper().replace(" ", "_")


def _cell(row: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _parse_sec_date(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    for fmt in _SEC_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_number(value: str | None) -> float | None:
    text = str(value or "").replace(",", "").replace("$", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_tsv_table(handle: io.TextIOBase) -> list[dict[str, str]]:
    reader = csv.DictReader(handle, delimiter="\t")
    rows: list[dict[str, str]] = []
    for raw in reader:
        rows.append({_normalize_header(str(key)): ("" if value is None else str(value)) for key, value in raw.items()})
    return rows


def _table_from_bytes(payload: bytes) -> list[dict[str, str]]:
    return _read_tsv_table(io.StringIO(payload.decode("utf-8-sig", errors="replace")))


def load_tables_from_zip(zip_path: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = Path(info.filename).name.upper()
            stem = Path(name).stem.upper()
            if not name.endswith(".TSV"):
                continue
            if stem not in REQUIRED_TABLES and stem not in OPTIONAL_TABLES:
                continue
            tables[stem] = _table_from_bytes(archive.read(info))
    return tables


def load_tables_from_directory(directory: Path) -> dict[str, list[dict[str, str]]]:
    tables: dict[str, list[dict[str, str]]] = {}
    for path in directory.iterdir():
        stem = path.stem.upper()
        if path.suffix.lower() != ".tsv":
            continue
        if stem not in REQUIRED_TABLES and stem not in OPTIONAL_TABLES:
            continue
        tables[stem] = _read_tsv_table(path.open(encoding="utf-8-sig"))
    return tables


def load_tables(source: Path) -> dict[str, list[dict[str, str]]]:
    if source.is_dir():
        return load_tables_from_directory(source)
    if zipfile.is_zipfile(source):
        return load_tables_from_zip(source)
    raise ValueError(f"Section-16 source must be a ZIP or extracted directory: {source}")


def _owner_index(rows: Iterable[Mapping[str, str]]) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for row in rows:
        accession = _cell(row, "ACCESSION_NUMBER")
        if not accession or accession in index:
            continue
        index[accession] = dict(row)
    return index


def _footnote_index(rows: Iterable[Mapping[str, str]]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for row in rows:
        accession = _cell(row, "ACCESSION_NUMBER")
        if not accession:
            continue
        index.setdefault(accession, []).append(_cell(row, "FOOTNOTE_TXT", "FOOTNOTE_TEXT"))
    return index


def parse_open_market_transactions(tables: Mapping[str, list[dict[str, str]]]) -> list[InsiderTransaction]:
    submissions = { _cell(row, "ACCESSION_NUMBER"): row for row in tables.get("SUBMISSION", []) if _cell(row, "ACCESSION_NUMBER") }
    owners = _owner_index(tables.get("REPORTINGOWNER", []))
    footnotes = _footnote_index(tables.get("FOOTNOTES", []))
    missing = [name for name in REQUIRED_TABLES if name not in tables]
    if missing:
        raise ValueError(f"SEC insider dataset is missing required tables: {', '.join(missing)}")

    transactions: list[InsiderTransaction] = []
    skipped_codes: dict[str, int] = {}
    for row in tables.get("NONDERIV_TRANS", []):
        code = normalize_transaction_code(_cell(row, "TRANS_CODE"))
        if not is_open_market_code(code):
            skipped_codes[code or "missing"] = skipped_codes.get(code or "missing", 0) + 1
            continue
        accession = _cell(row, "ACCESSION_NUMBER")
        submission = submissions.get(accession, {})
        owner = owners.get(accession, {})
        document_type = _cell(submission, "DOCUMENT_TYPE")
        if document_type and document_type.split("/")[0] not in {"3", "4", "5"}:
            continue
        shares = _parse_number(_cell(row, "TRANS_SHARES"))
        price = _parse_number(_cell(row, "TRANS_PRICEPERSHARE"))
        value = None if shares is None or price is None else shares * price
        relationship = _cell(owner, "RPTOWNER_RELATIONSHIP").upper()
        footnote_texts = footnotes.get(accession, [])
        is_10b5_1 = truthy_flag(_cell(submission, "AFF10B5ONE", "AFF_10B5ONE")) or footnote_indicates_10b5_1(
            *footnote_texts,
            _cell(submission, "REMARKS"),
        )
        filed_at = _parse_sec_date(_cell(submission, "FILING_DATE"))
        trans_date = _parse_sec_date(_cell(row, "TRANS_DATE")) or filed_at
        if not accession or not filed_at:
            continue
        transactions.append(
            InsiderTransaction(
                accession_number=accession,
                ticker=_cell(submission, "ISSUERTRADINGSYMBOL").upper(),
                issuer_cik=_cell(submission, "ISSUERCIK") or None,
                issuer_name=_cell(submission, "ISSUERNAME") or None,
                owner_cik=_cell(owner, "RPTOWNERCIK") or None,
                owner_name=_cell(owner, "RPTOWNERNAME") or None,
                owner_title=_cell(owner, "RPTOWNER_TITLE") or None,
                is_director="DIRECTOR" in relationship,
                is_officer="OFFICER" in relationship,
                is_ten_percent_owner="TENPERCENTOWNER" in relationship or "TEN_PERCENT" in relationship,
                transaction_date=trans_date or filed_at,
                filed_at=filed_at,
                transaction_code=code,
                acquired_disposed=_cell(row, "TRANS_ACQUIRED_DISP_CD").upper() or None,
                shares=shares,
                price_per_share=price,
                value_usd=value,
                is_10b5_1=is_10b5_1,
                is_derivative=False,
                source="sec_quarterly_zip",
                footnote_ids=tuple(
                    item
                    for item in (
                        _cell(row, "TRANS_CODE_FN"),
                        _cell(row, "TRANS_SHARES_FN"),
                        _cell(row, "TRANS_PRICEPERSHARE_FN"),
                    )
                    if item
                ),
                document_type=document_type or None,
            )
        )
    if skipped_codes:
        _log.debug("Excluded non-open-market Section-16 codes: %s", skipped_codes)
    return transactions


def parse_source(source: Path) -> list[InsiderTransaction]:
    return parse_open_market_transactions(load_tables(source))


__all__ = [
    "load_tables",
    "parse_open_market_transactions",
    "parse_source",
    "quarterly_zip_url",
]
