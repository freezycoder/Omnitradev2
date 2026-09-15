from __future__ import annotations

import csv
import io
import logging
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

from config.etf import DEFAULT_ETF_UNIVERSE
from config.form13f import VALUE_UNITS_CUTOVER, zip_url
from config.form13f_taxonomy_v1 import ISSUER_NAME_TO_TICKER, CUSIP8_TO_TICKER, normalize_cik, normalize_cusip8
from providers.events.form13f_models import HoldingPosition, parse_iso_date


_log = logging.getLogger(__name__)

REQUIRED_TABLES = ("SUBMISSION", "COVERPAGE", "INFOTABLE")
OPTIONAL_TABLES = ("SUMMARYPAGE",)
_SEC_DATE_FORMATS = ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%B-%Y")
_OPTION_FLAGS = frozenset({"PUT", "CALL"})
_ETF_TITLE_TOKENS = ("ETF", "EXCHANGE TRADED", "UNIT BEN INT", "UT BEN INT")


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
    candidates = (text, text.title(), text.upper())
    for candidate in candidates:
        for fmt in _SEC_DATE_FORMATS:
            try:
                return datetime.strptime(candidate, fmt).date().isoformat()
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
        rows.append(
            {_normalize_header(str(key)): ("" if value is None else str(value)) for key, value in raw.items()}
        )
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
    raise ValueError(f"Form 13F source must be a ZIP or extracted directory: {source}")


def map_cusip_to_ticker(cusip: str | None, issuer_name: str | None = None) -> str | None:
    stem = normalize_cusip8(cusip)
    if stem and stem in CUSIP8_TO_TICKER:
        return CUSIP8_TO_TICKER[stem]
    name = " ".join(str(issuer_name or "").upper().split())
    if name and name in ISSUER_NAME_TO_TICKER:
        return ISSUER_NAME_TO_TICKER[name]
    return None


def _value_to_usd(raw_value: float | None, filed_at: str | None) -> float | None:
    if raw_value is None:
        return None
    filed = parse_iso_date(filed_at)
    cutover = date.fromisoformat(VALUE_UNITS_CUTOVER)
    if filed is None or filed < cutover:
        return raw_value * 1000.0
    return raw_value


def _is_option(put_call: str | None) -> bool:
    return str(put_call or "").strip().upper() in _OPTION_FLAGS


def _looks_like_etf(ticker: str | None, title: str | None) -> bool:
    if ticker and ticker.upper() in DEFAULT_ETF_UNIVERSE:
        return True
    upper_title = str(title or "").upper()
    return any(token in upper_title for token in _ETF_TITLE_TOKENS)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().upper() in {"Y", "YES", "TRUE", "1"}


def parse_holdings(tables: Mapping[str, list[dict[str, str]]]) -> list[HoldingPosition]:
    missing = [name for name in REQUIRED_TABLES if name not in tables]
    if missing:
        raise ValueError(f"SEC 13F dataset is missing required tables: {', '.join(missing)}")

    submissions = {
        _cell(row, "ACCESSION_NUMBER"): row
        for row in tables.get("SUBMISSION", [])
        if _cell(row, "ACCESSION_NUMBER")
    }
    coverpages = {
        _cell(row, "ACCESSION_NUMBER"): row
        for row in tables.get("COVERPAGE", [])
        if _cell(row, "ACCESSION_NUMBER")
    }

    holdings: list[HoldingPosition] = []
    skipped = 0
    for row in tables.get("INFOTABLE", []):
        accession = _cell(row, "ACCESSION_NUMBER")
        submission = submissions.get(accession, {})
        cover = coverpages.get(accession, {})
        filed_at = _parse_sec_date(_cell(submission, "FILING_DATE"))
        reportable = _parse_sec_date(
            _cell(submission, "PERIODOFREPORT") or _cell(cover, "REPORTCALENDARORQUARTER")
        )
        manager_cik = normalize_cik(_cell(submission, "CIK", "FILINGMANAGER_CIK"))
        if not accession or not filed_at or not reportable or not manager_cik:
            skipped += 1
            continue
        put_call = _cell(row, "PUTCALL").upper() or None
        if _is_option(put_call):
            skipped += 1
            continue
        shares_type = _cell(row, "SSHPRNAMTTYPE").upper() or None
        if shares_type and shares_type not in {"SH", "SHARES"}:
            skipped += 1
            continue
        cusip = normalize_cusip8(_cell(row, "CUSIP"))
        if not cusip:
            skipped += 1
            continue
        issuer_name = _cell(row, "NAMEOFISSUER") or None
        title = _cell(row, "TITLEOFCLASS") or None
        ticker = map_cusip_to_ticker(cusip, issuer_name)
        if _looks_like_etf(ticker, title):
            skipped += 1
            continue
        raw_value = _parse_number(_cell(row, "VALUE"))
        holdings.append(
            HoldingPosition(
                accession_number=accession,
                manager_cik=manager_cik,
                manager_name=_cell(cover, "FILINGMANAGER_NAME") or None,
                reportable_quarter=reportable,
                filed_at=filed_at,
                cusip=cusip,
                ticker=ticker,
                issuer_name=issuer_name,
                title_of_class=title,
                shares=_parse_number(_cell(row, "SSHPRNAMT")),
                value_usd=_value_to_usd(raw_value, filed_at),
                put_call=put_call,
                shares_type=shares_type,
                submission_type=_cell(submission, "SUBMISSIONTYPE") or None,
                is_amendment=_truthy(_cell(cover, "ISAMENDMENT"))
                or str(_cell(submission, "SUBMISSIONTYPE")).upper().endswith("/A"),
                source="sec_form13f_zip",
            )
        )
    if skipped:
        _log.debug("Skipped %s 13F infotable rows (options, non-share, unmapped, or ETF).", skipped)
    return _resolve_amendments(holdings)


def _amendment_rank(row: HoldingPosition) -> tuple[str, str, str]:
    submission = (row.submission_type or "").upper()
    kind = "1-amendment" if row.is_amendment or submission.endswith("/A") else "0-initial"
    return (row.filed_at, kind, row.accession_number)


def _resolve_amendments(holdings: Iterable[HoldingPosition]) -> list[HoldingPosition]:
    grouped: dict[tuple[str, str], list[HoldingPosition]] = {}
    for row in holdings:
        grouped.setdefault((row.manager_cik, row.reportable_quarter), []).append(row)
    resolved: list[HoldingPosition] = []
    for rows in grouped.values():
        latest_accession = max(rows, key=_amendment_rank).accession_number
        resolved.extend(row for row in rows if row.accession_number == latest_accession)
    return resolved


def parse_source(source: Path) -> list[HoldingPosition]:
    return parse_holdings(load_tables(source))


def dataset_url(relative_path: str) -> str:
    return zip_url(relative_path)


__all__ = [
    "dataset_url",
    "load_tables",
    "map_cusip_to_ticker",
    "parse_holdings",
    "parse_source",
]
