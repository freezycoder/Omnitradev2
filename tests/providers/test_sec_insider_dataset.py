from __future__ import annotations

import zipfile
from pathlib import Path

from providers.events.sec_insider_dataset import parse_source


def _write_tsv(path: Path, header: str, rows: list[str]) -> None:
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_sec_dataset_keeps_open_market_ps_and_drops_awards_gifts_exercises_tax(tmp_path: Path):
    directory = tmp_path / "2026q1"
    directory.mkdir()
    _write_tsv(
        directory / "SUBMISSION.tsv",
        "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERNAME\tISSUERTRADINGSYMBOL\tAFF10B5ONE\tREMARKS",
        [
            "A1\t02-JAN-2024\t4\t1\tAAA Inc\tAAA\t0\t",
            "A2\t03-JAN-2024\t4\t1\tAAA Inc\tAAA\t0\t",
            "A3\t04-JAN-2024\t4\t1\tAAA Inc\tAAA\t0\t",
            "A4\t05-JAN-2024\t4\t1\tAAA Inc\tAAA\t0\taward",
            "A5\t06-JAN-2024\t4\t1\tAAA Inc\tAAA\t1\tRule 10b5-1 plan",
        ],
    )
    _write_tsv(
        directory / "REPORTINGOWNER.tsv",
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE",
        [
            "A1\t101\tBuyer One\tDIRECTOR\tDirector",
            "A2\t102\tSeller One\tOFFICER\tCFO",
            "A3\t103\tGift One\tDIRECTOR\tDirector",
            "A4\t104\tAward One\tOFFICER\tCEO",
            "A5\t105\tPlan One\tOFFICER\tCEO",
        ],
    )
    _write_tsv(
        directory / "NONDERIV_TRANS.tsv",
        "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD",
        [
            "A1\t1\t02-JAN-2024\tP\t1000\t10\tA",
            "A2\t2\t03-JAN-2024\tS\t500\t12\tD",
            "A3\t3\t04-JAN-2024\tG\t100\t0\tD",
            "A4\t4\t05-JAN-2024\tA\t2000\t0\tA",
            "A5\t5\t06-JAN-2024\tP\t800\t11\tA",
        ],
    )
    _write_tsv(
        directory / "FOOTNOTES.tsv",
        "ACCESSION_NUMBER\tFOOTNOTE_ID\tFOOTNOTE_TXT",
        ["A5\tF1\tThe purchase was made pursuant to a Rule 10b5-1 trading plan."],
    )

    rows = parse_source(directory)
    codes = {row.transaction_code for row in rows}
    assert codes == {"P", "S"}
    planned = [row for row in rows if row.is_10b5_1]
    assert len(planned) == 1
    assert planned[0].accession_number == "A5"
    assert any(row.ticker == "AAA" and row.transaction_code == "P" and not row.is_10b5_1 for row in rows)


def test_sec_dataset_reads_zip(tmp_path: Path):
    directory = tmp_path / "raw"
    directory.mkdir()
    (directory / "SUBMISSION.tsv").write_text(
        "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERNAME\tISSUERTRADINGSYMBOL\n"
        "Z1\t15-FEB-2024\t4\t9\tZip Co\tZIP\n",
        encoding="utf-8",
    )
    (directory / "REPORTINGOWNER.tsv").write_text(
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\tRPTOWNER_TITLE\n"
        "Z1\t9\tZip Owner\tDIRECTOR\tDirector\n",
        encoding="utf-8",
    )
    (directory / "NONDERIV_TRANS.tsv").write_text(
        "ACCESSION_NUMBER\tNONDERIV_TRANS_SK\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
        "Z1\t1\t15-FEB-2024\tP\t10\t5\tA\n",
        encoding="utf-8",
    )
    zip_path = tmp_path / "2024q1_insider.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        for path in directory.iterdir():
            archive.write(path, arcname=path.name)

    rows = parse_source(zip_path)
    assert len(rows) == 1
    assert rows[0].ticker == "ZIP"
    assert rows[0].value_usd == 50.0
    assert rows[0].source == "sec_quarterly_zip"
