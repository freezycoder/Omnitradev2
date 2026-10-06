from __future__ import annotations

import json
from pathlib import Path

from application.form144_shadow_service import Form144ShadowService
from domain.research.form144_fixture import aligned_form144_inputs
from providers.events.form4_sale_store import discover_form4_keep_store, form4_sales_from_payload
from storage.repositories.form144_repository import Form144Repository


def test_keep_store_discovery_reports_absence_on_main(tmp_path: Path) -> None:
    missing = tmp_path / "section16_cache" / "open_market_transactions.json"
    discovered = discover_form4_keep_store(missing)
    assert discovered["present"] is False
    assert discovered["sale_count"] == 0
    assert "No dedicated Form 4 KEEP store" in discovered["notes"]


def test_keep_store_reads_section16_json(tmp_path: Path) -> None:
    path = tmp_path / "open_market_transactions.json"
    path.write_text(
        json.dumps(
            {
                "transactions": [
                    {
                        "accession_number": "a1",
                        "ticker": "AAA",
                        "issuer_cik": "0000320193",
                        "owner_cik": "0001000001",
                        "owner_name": "Affiliate",
                        "filed_at": "2023-03-18",
                        "transaction_date": "2023-03-18",
                        "transaction_code": "S",
                        "acquired_disposed": "D",
                        "shares": 1000,
                        "value_usd": 15000,
                        "is_derivative": False,
                    },
                    {
                        "accession_number": "a2",
                        "ticker": "AAA",
                        "issuer_cik": "0000320193",
                        "owner_cik": "0001000001",
                        "filed_at": "2023-03-18",
                        "transaction_date": "2023-03-18",
                        "transaction_code": "P",
                        "acquired_disposed": "A",
                        "shares": 1000,
                        "is_derivative": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    discovered = discover_form4_keep_store(path)
    assert discovered["present"] is True
    assert discovered["sale_count"] == 1
    sales = form4_sales_from_payload(json.loads(path.read_text(encoding="utf-8")))
    assert sales[0].transaction_code == "S"


def test_shadow_service_never_flips_live(tmp_path: Path) -> None:
    notices, sales, _panel = aligned_form144_inputs(mode="lead")
    repository = Form144Repository(tmp_path / "notices.json")
    service = Form144ShadowService(repository, last_run_path=tmp_path / "last.json")
    ingest = service.ingest_sec_source  # attribute exists for XML/JSON ingest
    assert callable(ingest)
    repository.replace_with(notices)
    payload = service.run_match_study(notices=notices, sales=sales, persist=True)
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["cannot_flip_live"] is True
    view = service.view_for_ticker("AAA", notices=notices, sales=sales, as_of="2023-06-01")
    assert view.applied_impact == 0
    assert view.modeled_impact == 0
