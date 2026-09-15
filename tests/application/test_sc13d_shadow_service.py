from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from application.sc13d_shadow_service import Sc13dShadowService, form4_buys_from_bundles
from domain.research.sc13d_event_study import price_panel_from_frames
from providers.events.sc13d_models import Sc13dFiling
from providers.events.sec_edgar_client import SecEventBundle, SecFilingEvent
from storage.repositories.sc13d_repository import Sc13dRepository


PURPOSE_ACTIVIST = (
    "The Reporting Person acquired the shares to seek board representation and "
    "may nominate directors to maximize shareholder value."
)


def _history(start: date, sessions: int, start_price: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=sessions)
    closes = [start_price + index * step for index in range(sessions)]
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": [1_000_000] * sessions},
        index=dates,
    )


def test_calibration_payload_is_not_run_without_cache(tmp_path: Path):
    service = Sc13dShadowService(
        repository=Sc13dRepository(tmp_path / "filings.json", tmp_path / "log.jsonl"),
        last_run_path=tmp_path / "last.json",
    )
    payload = service.calibration_payload()
    assert payload["mode"] == "shadow"
    assert payload["live_ranking_changes"] is False
    assert payload["applied_impact"] == 0
    assert payload["status"] == "not_run"


def test_shadow_service_persists_log_and_never_applies_impact(tmp_path: Path):
    start = date(2015, 1, 2)
    spy = _history(start, 400, 100.0, 0.02)
    stocks = {
        "AAA": _history(start, 400, 20.0, 0.08),
        "CCC": _history(start, 400, 20.0, 0.07),
        "DDD": _history(start, 400, 20.0, 0.09),
    }
    filings: list[Sc13dFiling] = []
    event_start = date(2016, 1, 4)
    for index in range(15):
        filed = event_start + timedelta(days=index * 21)
        for ticker, reporting in (("AAA", "101"), ("CCC", "102"), ("DDD", "105")):
            filings.append(
                Sc13dFiling(
                    accession_number=f"{ticker}-{index}",
                    form="SC 13D",
                    filed_at=filed.isoformat(),
                    ticker=ticker,
                    issuer_cik="1",
                    issuer_name=ticker,
                    reporting_cik=f"0000000{reporting}",
                    reporting_name="Fund",
                    url="https://sec",
                    purpose_text=PURPOSE_ACTIVIST,
                    percent_of_class=6.0,
                )
            )
    panel = price_panel_from_frames(stocks, spy, ticker_sector={"AAA": "XLK", "CCC": "XLK", "DDD": "XLK"})
    service = Sc13dShadowService(
        repository=Sc13dRepository(tmp_path / "filings.json", tmp_path / "log.jsonl"),
        last_run_path=tmp_path / "last.json",
    )
    payload = service.run_event_study(panel, filings=filings)
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == 0
    assert (tmp_path / "log.jsonl").exists()
    cached = service.calibration_payload()
    assert cached["verdict"] == payload["verdict"]
    assert cached["live_ranking_changes"] is False


def test_form4_buys_from_bundles_ignore_clusters():
    bundle = SecEventBundle(
        ticker="AAA",
        cik="1",
        status="available",
        retrieved_at="2016-03-01",
        events=[
            SecFilingEvent("4", "2016-03-01", "insider_purchase", 1, 2, "buy", "https://sec", "a1"),
            SecFilingEvent("4 cluster", "2016-03-01", "insider_purchase_cluster", 1, 3, "cluster", "https://sec", "cluster"),
        ],
    )
    events = form4_buys_from_bundles([bundle])
    assert len(events) == 1
    assert events[0].accession_number == "a1"
