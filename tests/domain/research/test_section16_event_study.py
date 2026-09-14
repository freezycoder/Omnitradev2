from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from application.section16_shadow_service import price_panel_from_frames
from config.section16 import (
    CLUSTER_MIN_INSIDERS,
    CLUSTER_WINDOW_DAYS,
    OPEN_MARKET_CODES,
    OVERLAP_ENRICHMENT_THRESHOLD_PCT,
    PRIMARY_SOURCE,
    SECTION16_APPLIED_IMPACT,
)
from domain.research.section16_event_study import audit_form4_overlap, evaluate_section16_experiment
from domain.scoring.section16_insider import build_section16_insider_view
from providers.events.sec_edgar_client import SecEventBundle, SecFilingEvent
from providers.events.section16_models import InsiderTransaction


def _history(start: date, sessions: int, start_price: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=sessions)
    closes = [start_price + index * step for index in range(sessions)]
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [value + 1 for value in closes],
            "Low": [value - 1 for value in closes],
            "Close": closes,
            "Volume": [1_000_000] * sessions,
        },
        index=dates,
    )


def _row(**overrides: object) -> InsiderTransaction:
    payload = {
        "accession_number": "0001",
        "ticker": "AAA",
        "issuer_cik": "1",
        "issuer_name": "AAA",
        "owner_cik": "101",
        "owner_name": "One",
        "owner_title": "Director",
        "is_director": True,
        "is_officer": False,
        "is_ten_percent_owner": False,
        "transaction_date": "2024-01-02",
        "filed_at": "2024-01-02",
        "transaction_code": "P",
        "acquired_disposed": "A",
        "shares": 1000.0,
        "price_per_share": 25.0,
        "value_usd": 25_000.0,
        "is_10b5_1": False,
        "is_derivative": False,
        "source": "sec_quarterly_zip",
    }
    payload.update(overrides)
    return InsiderTransaction(**payload)  # type: ignore[arg-type]


def _aligned_inputs():
    start = date(2024, 1, 2)
    spy = _history(start, 180, 100.0, 0.05)
    sector = _history(start, 180, 50.0, 0.04)
    stocks = {
        "AAA": _history(start, 180, 20.0, 0.45),
        "BBB": _history(start, 180, 20.0, 0.01),
        "CCC": _history(start, 180, 20.0, 0.40),
    }
    transactions: list[InsiderTransaction] = []
    edgar: list[SecEventBundle] = []
    for index in range(15):
        filed = (start + timedelta(days=index * 8)).isoformat()
        for owner in ("101", "102", "103"):
            transactions.append(
                _row(
                    accession_number=f"AAA-{index}-{owner}",
                    ticker="AAA",
                    owner_cik=owner,
                    filed_at=filed,
                    transaction_date=filed,
                )
            )
        edgar.append(
            SecEventBundle(
                ticker="AAA",
                cik="1",
                status="available",
                retrieved_at=filed,
                events=[
                    SecFilingEvent(
                        "4",
                        filed,
                        "insider_purchase",
                        1,
                        2,
                        "purchase",
                        "https://sec",
                        f"AAA-{index}-101",
                    )
                ],
            )
        )
        transactions.append(
            _row(
                accession_number=f"BBB-{index}",
                ticker="BBB",
                owner_cik="201",
                filed_at=filed,
                transaction_date=filed,
                transaction_code="S",
                acquired_disposed="D",
                value_usd=12_000.0,
            )
        )
    panel = price_panel_from_frames(
        stocks,
        spy,
        sector_histories={"XLK": sector},
        ticker_sector={"AAA": "XLK", "BBB": "XLK", "CCC": "XLK"},
    )
    return transactions, panel, edgar


def test_protocol_is_frozen_before_eval():
    assert OPEN_MARKET_CODES == frozenset({"P", "S"})
    assert CLUSTER_MIN_INSIDERS == 3
    assert CLUSTER_WINDOW_DAYS == 60
    assert OVERLAP_ENRICHMENT_THRESHOLD_PCT == 70.0
    assert PRIMARY_SOURCE.startswith("sec")
    assert SECTION16_APPLIED_IMPACT == 0


def test_aligned_buy_intensity_and_clusters_pass_walk_forward():
    transactions, panel, edgar = _aligned_inputs()
    payload = evaluate_section16_experiment(
        transactions,
        panel,
        edgar_bundles=edgar,
        xml_path_available=True,
    )
    assert payload["status"] == "shadow_research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == 0
    assert payload["verdict"] == "SUCCESS"
    assert payload["positive_folds"] >= 2
    assert payload["protocol"]["primary_source"].startswith("sec")


def test_no_lift_after_filters_fails():
    start = date(2024, 1, 2)
    flat = _history(start, 120, 20.0, 0.0)
    spy = _history(start, 120, 100.0, 0.0)
    transactions = [
        _row(filed_at=(start + timedelta(days=index * 6)).isoformat(), accession_number=str(index))
        for index in range(12)
    ]
    panel = price_panel_from_frames({"AAA": flat}, spy, ticker_sector={"AAA": "XLK"})
    payload = evaluate_section16_experiment(transactions, panel, xml_path_available=True)
    assert payload["verdict"] in {"FAIL", "INCONCLUSIVE"}


def test_missing_xml_path_fails_freshness_gate():
    transactions, panel, edgar = _aligned_inputs()
    payload = evaluate_section16_experiment(
        transactions,
        panel,
        edgar_bundles=edgar,
        xml_path_available=False,
    )
    assert payload["verdict"] == "FAIL"
    assert "XML" in payload["reason"]


def test_overlap_threshold_is_documented_before_run():
    transactions = [_row(accession_number="dup"), _row(accession_number="new", owner_cik="102")]
    bundle = SecEventBundle(
        ticker="AAA",
        cik="1",
        status="available",
        retrieved_at="2024-01-02",
        events=[SecFilingEvent("4", "2024-01-02", "insider_purchase", 1, 2, "p", "https://sec", "dup")],
    )
    audit = audit_form4_overlap(transactions, [bundle])
    assert audit["threshold_pct"] == 70.0
    assert audit["overlap_pct"] == 50.0
    assert audit["stream_role"] == "candidate_new_stream"


def test_shadow_view_never_applies_live_impact():
    view = build_section16_insider_view(
        ticker="AAA",
        transactions=[
            _row(owner_cik="101"),
            _row(owner_cik="102", accession_number="2"),
            _row(owner_cik="103", accession_number="3"),
        ],
        as_of="2024-01-02",
        freshness_source="edgar_form4_xml",
    )
    assert view.mode == "shadow"
    assert view.applied_impact == 0
    assert view.cluster_flag is True
    assert view.modeled_impact > 0
