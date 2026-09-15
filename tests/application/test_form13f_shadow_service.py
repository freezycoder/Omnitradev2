from __future__ import annotations

import zipfile
from pathlib import Path

from application.form13f_shadow_service import Form13FShadowService
from domain.research.form13f_fixture import aligned_form13f_inputs
from providers.events.form13f_dataset import parse_source
from storage.repositories.form13f_repository import Form13FRepository


def test_ingest_and_event_study_stay_shadow_only(tmp_path: Path) -> None:
    holdings, panel = aligned_form13f_inputs(with_burst=True)
    service = Form13FShadowService(
        repository=Form13FRepository(tmp_path / "holdings.json"),
        last_run_path=tmp_path / "last.json",
    )
    payload = service.run_event_study(panel, holdings=holdings, persist=True)
    assert payload["status"] == "shadow_research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == 0
    assert (tmp_path / "last.json").exists()
    view = service.view_for_ticker("AAA", holdings=holdings, as_of="2022-05-31")
    assert view.applied_impact == 0
    assert view.mode == "shadow"


def test_parse_source_ingest_stays_shadow(tmp_path: Path) -> None:
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT\n"
        "0001\t15-MAY-2021\t13F-HR\t0001037389\t31-MAR-2021\n"
    )
    cover = (
        "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTTYPE\tFILINGMANAGER_NAME\n"
        "0001\t31-MAR-2021\tN\t\tRENAISSANCE TECHNOLOGIES LLC\n"
    )
    info = (
        "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL\n"
        "0001\t1\tAPPLE INC\tCOM\t037833100\t\t100\t10\tSH\t\n"
    )
    zip_path = tmp_path / "q.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("SUBMISSION.tsv", submission)
        archive.writestr("COVERPAGE.tsv", cover)
        archive.writestr("INFOTABLE.tsv", info)
    service = Form13FShadowService(repository=Form13FRepository(tmp_path / "holdings.json"))
    result = service.ingest_sec_source(zip_path, replace=True)
    assert result["mode"] == "shadow"
    assert result["live_ranking_changes"] is False
    assert result["ingested"] == 1
    assert parse_source(zip_path)[0].ticker == "AAPL"
