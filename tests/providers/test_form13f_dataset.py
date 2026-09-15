from __future__ import annotations

import zipfile
from datetime import date, timedelta
from pathlib import Path

from config.form13f import VALUE_UNITS_CUTOVER
from providers.events.form13f_dataset import map_cusip_to_ticker, parse_holdings, parse_source


def _write_zip(path: Path, tables: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in tables.items():
            archive.writestr(name, payload)
    return path


def test_cusip_and_issuer_name_map_to_ticker() -> None:
    assert map_cusip_to_ticker("037833100") == "AAPL"
    assert map_cusip_to_ticker(None, "MICROSOFT CORP") == "MSFT"


def test_value_units_cutover_and_option_rows(tmp_path: Path) -> None:
    before = date.fromisoformat(VALUE_UNITS_CUTOVER) - timedelta(days=10)
    after = date.fromisoformat(VALUE_UNITS_CUTOVER)
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
        f"0001\t{before.strftime('%d-%b-%Y').upper()}\t13F-HR\t0001037389\t31-DEC-2022\n"
        f"0002\t{after.strftime('%d-%b-%Y').upper()}\t13F-HR\t0001037389\t31-MAR-2023\n"
    )
    cover = (
        "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTTYPE\tFILINGMANAGER_NAME\n"
        "0001\t31-DEC-2022\tN\t\tRENAISSANCE TECHNOLOGIES LLC\n"
        "0002\t31-MAR-2023\tN\t\tRENAISSANCE TECHNOLOGIES LLC\n"
    )
    info = (
        "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\n"
        "0001\t1\tAPPLE INC\tCOM\t037833100\t\t100\t10\tSH\t\n"
        "0001\t2\tAPPLE INC\tCOM\t037833100\t\t50\t5\tSH\tPUT\n"
        "0002\t3\tAPPLE INC\tCOM\t037833100\t\t100\t10\tSH\t\n"
        "0002\t4\tSPDR S&P 500\tETF\t78462F103\t\t80\t8\tSH\t\n"
    )
    zip_path = _write_zip(
        tmp_path / "sample_form13f.zip",
        {"SUBMISSION.tsv": submission, "COVERPAGE.tsv": cover, "INFOTABLE.tsv": info},
    )
    rows = parse_source(zip_path)
    assert [row.ticker for row in rows] == ["AAPL", "AAPL"]
    pre = next(row for row in rows if row.accession_number == "0001")
    post = next(row for row in rows if row.accession_number == "0002")
    assert pre.value_usd == 100_000.0
    assert post.value_usd == 100.0
    assert all(row.put_call in {None, ""} for row in rows)


def test_latest_amendment_replaces_initial_holdings() -> None:
    tables = {
        "SUBMISSION": [
            {
                "ACCESSION_NUMBER": "0001",
                "FILING_DATE": "15-MAY-2021",
                "SUBMISSIONTYPE": "13F-HR",
                "CIK": "0001037389",
                "PERIODOFREPORT": "31-MAR-2021",
            },
            {
                "ACCESSION_NUMBER": "0002",
                "FILING_DATE": "20-MAY-2021",
                "SUBMISSIONTYPE": "13F-HR/A",
                "CIK": "0001037389",
                "PERIODOFREPORT": "31-MAR-2021",
            },
        ],
        "COVERPAGE": [
            {
                "ACCESSION_NUMBER": "0001",
                "REPORTCALENDARORQUARTER": "31-MAR-2021",
                "ISAMENDMENT": "N",
                "FILINGMANAGER_NAME": "RENAISSANCE",
            },
            {
                "ACCESSION_NUMBER": "0002",
                "REPORTCALENDARORQUARTER": "31-MAR-2021",
                "ISAMENDMENT": "Y",
                "AMENDMENTTYPE": "RESTATEMENT",
                "FILINGMANAGER_NAME": "RENAISSANCE",
            },
        ],
        "INFOTABLE": [
            {
                "ACCESSION_NUMBER": "0001",
                "NAMEOFISSUER": "APPLE INC",
                "TITLEOFCLASS": "COM",
                "CUSIP": "037833100",
                "VALUE": "10",
                "SSHPRNAMT": "1",
                "SSHPRNAMTTYPE": "SH",
                "PUTCALL": "",
            },
            {
                "ACCESSION_NUMBER": "0002",
                "NAMEOFISSUER": "MICROSOFT CORP",
                "TITLEOFCLASS": "COM",
                "CUSIP": "594918104",
                "VALUE": "20",
                "SSHPRNAMT": "2",
                "SSHPRNAMTTYPE": "SH",
                "PUTCALL": "",
            },
        ],
    }
    rows = parse_holdings(tables)
    assert len(rows) == 1
    assert rows[0].ticker == "MSFT"
    assert rows[0].is_amendment is True
