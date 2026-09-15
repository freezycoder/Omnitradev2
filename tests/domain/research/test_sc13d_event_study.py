from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from config.sc13d import MIN_PRIMARY_N, PRIMARY_WINDOW_KEY, SC13D_APPLIED_IMPACT
from domain.research.sc13d_event_study import (
    evaluate_sc13d_experiment,
    flag_prior_13g_conversions,
    price_panel_from_frames,
    window_return_pct,
)
from providers.events.sc13d_models import Form4BuyEvent, Sc13dFiling


PURPOSE_ACTIVIST = (
    "The Reporting Person acquired the shares to seek board representation and "
    "may nominate directors. The Reporting Person intends to pursue strategic "
    "alternatives to maximize shareholder value."
)
PURPOSE_PASSIVE = (
    "The securities were acquired solely for investment. The Reporting Person has "
    "no present plans or proposals and did not acquire the shares for the purpose "
    "of changing or influencing control of the issuer."
)
PURPOSE_FINANCING = (
    "The shares were issued in a private placement PIPE financing in connection "
    "with a convertible note."
)


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


def _piecewise_history(
    start: date,
    sessions: int,
    event_date: date,
    pre_step: float,
    post_step: float,
    start_price: float = 20.0,
) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=sessions)
    event_ts = pd.Timestamp(event_date)
    cutoff = event_ts - pd.Timedelta(days=3)
    closes: list[float] = []
    price = start_price
    for stamp in dates:
        closes.append(price)
        price += pre_step if stamp < cutoff else post_step
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


def _filing(**overrides: object) -> Sc13dFiling:
    payload = {
        "accession_number": "0001",
        "form": "SC 13D",
        "filed_at": "2016-03-01",
        "ticker": "AAA",
        "issuer_cik": "0000000001",
        "issuer_name": "AAA Inc",
        "reporting_cik": "0000000100",
        "reporting_name": "Star Fund",
        "url": "https://www.sec.gov/Archives/edgar/data/1/0001/doc.htm",
        "purpose_text": PURPOSE_ACTIVIST,
        "percent_of_class": 6.4,
        "source": "fixture",
    }
    payload.update(overrides)
    return Sc13dFiling(**payload)  # type: ignore[arg-type]


def _aligned_inputs():
    start = date(2015, 1, 2)
    spy = _history(start, 520, 100.0, 0.02)
    sector = _history(start, 520, 50.0, 0.01)
    stocks = {
        "AAA": _history(start, 520, 20.0, 0.08),
        "BBB": _history(start, 520, 20.0, 0.00),
        "CCC": _history(start, 520, 20.0, 0.07),
        "DDD": _history(start, 520, 20.0, 0.09),
    }
    filings: list[Sc13dFiling] = []
    form4: list[Form4BuyEvent] = []
    event_start = date(2016, 1, 4)
    for index in range(15):
        filed = event_start + timedelta(days=index * 21)
        for ticker, reporting in (("AAA", "101"), ("CCC", "102"), ("DDD", "105")):
            filings.append(
                _filing(
                    accession_number=f"{ticker}-{index}",
                    ticker=ticker,
                    reporting_cik=f"0000000{reporting}",
                    filed_at=filed.isoformat(),
                )
            )
        filings.append(
            _filing(
                accession_number=f"BBB-{index}",
                ticker="BBB",
                reporting_cik="0000000103",
                filed_at=filed.isoformat(),
                purpose_text=PURPOSE_PASSIVE,
            )
        )
        filings.append(
            _filing(
                accession_number=f"FIN-{index}",
                ticker="BBB",
                reporting_cik="0000000106",
                filed_at=filed.isoformat(),
                purpose_text=PURPOSE_FINANCING,
            )
        )
        if index % 5 == 0:
            form4.append(Form4BuyEvent("AAA", filed.isoformat(), f"F4-{index}"))
    panel = price_panel_from_frames(
        stocks,
        spy,
        sector_histories={"XLK": sector},
        ticker_sector={"AAA": "XLK", "BBB": "XLK", "CCC": "XLK", "DDD": "XLK"},
    )
    return filings, panel, form4


def test_window_return_uses_close_to_close_event_time():
    start = date(2016, 1, 4)
    history = _history(start, 10, 100.0, 1.0)
    close = pd.to_numeric(history["Close"])
    close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
    result = window_return_pct(close, date(2016, 1, 5), 0, 1)
    assert result == pytest.approx(2.0)


def test_aligned_activist_filings_pass_walk_forward():
    filings, panel, form4 = _aligned_inputs()
    payload = evaluate_sc13d_experiment(filings, panel, form4_buys=form4)
    assert payload["status"] == "shadow_research_only"
    assert payload["deployment_guard"]["live_ranking_changes"] is False
    assert payload["deployment_guard"]["applied_impact"] == SC13D_APPLIED_IMPACT
    assert payload["filters"]["passive_excluded"] == 15
    assert payload["filters"]["financing_excluded"] == 15
    assert payload["data_quality"]["activist_complete_primary_window"] >= MIN_PRIMARY_N
    assert payload["verdict"] == "SUCCESS"
    assert payload["positive_folds"] >= 2
    assert payload["orthogonality_vs_form4"]["role"] == "diagnostic_only"
    assert payload["orthogonality_vs_form4"]["overlap_events"] >= 1


def test_null_post_file_car_fails():
    start = date(2015, 1, 2)
    flat = _history(start, 400, 20.0, 0.0)
    spy = _history(start, 400, 100.0, 0.0)
    stocks = {"AAA": flat, "CCC": flat, "DDD": flat}
    filings = []
    event_start = date(2016, 1, 4)
    for index in range(15):
        filed = event_start + timedelta(days=index * 14)
        for ticker, reporting in (("AAA", "101"), ("CCC", "102"), ("DDD", "105")):
            filings.append(
                _filing(
                    accession_number=f"{ticker}-{index}",
                    ticker=ticker,
                    reporting_cik=f"0000000{reporting}",
                    filed_at=filed.isoformat(),
                )
            )
    panel = price_panel_from_frames(stocks, spy, ticker_sector={"AAA": "XLK", "CCC": "XLK", "DDD": "XLK"})
    payload = evaluate_sc13d_experiment(filings, panel)
    assert payload["data_quality"]["activist_complete_primary_window"] >= MIN_PRIMARY_N
    assert payload["verdict"] == "FAIL"
    assert "Sparsity" not in payload["reason"]


def test_sparsity_below_registered_n_fails():
    start = date(2015, 1, 2)
    spy = _history(start, 200, 100.0, 0.0)
    stock = _history(start, 200, 20.0, 0.5)
    filings = [
        _filing(accession_number="1", filed_at="2016-03-01"),
        _filing(accession_number="2", filed_at="2016-06-01", reporting_cik="0000000101"),
    ]
    panel = price_panel_from_frames({"AAA": stock}, spy, ticker_sector={"AAA": "XLK"})
    payload = evaluate_sc13d_experiment(filings, panel)
    assert payload["verdict"] == "FAIL"
    assert "Sparsity" in payload["reason"]


def test_runup_only_signal_fails():
    start = date(2015, 1, 2)
    spy = _history(start, 520, 100.0, 0.0)
    stocks = {}
    filings: list[Sc13dFiling] = []
    event_start = date(2016, 1, 4)
    for index in range(15):
        filed = event_start + timedelta(days=index * 21)
        for suffix in ("A", "B", "C"):
            ticker = f"T{index:02d}{suffix}"
            stocks[ticker] = _piecewise_history(start, 520, filed, pre_step=0.6, post_step=0.0)
            filings.append(
                _filing(
                    accession_number=f"{ticker}-{index}",
                    ticker=ticker,
                    reporting_cik=f"0000001{index:03d}{ord(suffix)}",
                    filed_at=filed.isoformat(),
                )
            )
    panel = price_panel_from_frames(stocks, spy)
    payload = evaluate_sc13d_experiment(filings, panel)
    assert payload["verdict"] == "FAIL"
    assert "run-up" in payload["reason"].lower() or "anticipated" in payload["reason"].lower()
    runup = payload["event_study"]["runup"]
    assert runup["mean_pct"] is not None and runup["mean_pct"] > 0
    primary = next(item for item in payload["event_study"]["post_windows"] if item["window"] == PRIMARY_WINDOW_KEY)
    assert not primary["significant_positive"]


def test_pre_2008_events_are_dropped_from_primary():
    start = date(2006, 1, 2)
    spy = _history(start, 300, 100.0, 0.0)
    stock = _history(start, 300, 20.0, 0.4)
    filings = [_filing(accession_number="old", filed_at="2007-06-01")]
    panel = price_panel_from_frames({"AAA": stock}, spy)
    payload = evaluate_sc13d_experiment(filings, panel)
    assert payload["data_quality"]["activist_events"] == 0
    assert payload["verdict"] == "FAIL"


def test_prior_13g_sets_conversion_flag():
    thirteen_d = [
        _filing(
            accession_number="d1",
            filed_at="2016-03-01",
            reporting_cik="0000000999",
        )
    ]
    thirteen_g = [
        _filing(
            accession_number="g1",
            form="SC 13G",
            filed_at="2015-06-01",
            reporting_cik="0000000999",
            purpose_text=PURPOSE_PASSIVE,
        )
    ]
    flagged = flag_prior_13g_conversions(thirteen_d, thirteen_g)
    assert flagged[0].conversion_prior_13g is True
    assert flagged[0].conversion_13g_to_13d is True
