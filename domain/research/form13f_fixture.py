from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from config.form13f_taxonomy_v1 import NAMED_NOTABLE_MANAGERS, PASSIVE_INDEX_MANAGERS
from domain.research.form13f_event_study import PricePanel, evaluate_form13f_experiment
from providers.events.form13f_models import HoldingPosition


NOTABLE_CIKS = tuple(NAMED_NOTABLE_MANAGERS.keys())[:3]
PASSIVE_CIKS = tuple(PASSIVE_INDEX_MANAGERS.keys())[:3]
SINGLE_CIK = tuple(NAMED_NOTABLE_MANAGERS.keys())[3]
FIXTURE_CUSIPS = {
    "AAA": "03783310",
    "ZZZ": "59491810",
    "YYY": "67066G10",
    "BBB": "02313510",
    "CCC": "02079K30",
    "DDD": "30303M10",
    "EEE": "11135F10",
}


def history_frame(start: date, sessions: int, start_price: float, step: float) -> pd.DataFrame:
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


def quarter_end(year: int, quarter: int) -> date:
    month = quarter * 3
    day = 31 if month in {3, 12} else 30
    return date(year, month, day)


def filing_date(period_end: date) -> date:
    filed = period_end + timedelta(days=45)
    while filed.weekday() >= 5:
        filed += timedelta(days=1)
    return filed


def holding(
    *,
    ticker: str,
    manager_cik: str,
    manager_name: str,
    reportable_quarter: str,
    filed_at: str,
    accession: str,
    value_usd: float = 50_000_000.0,
) -> HoldingPosition:
    return HoldingPosition(
        accession_number=accession,
        manager_cik=manager_cik,
        manager_name=manager_name,
        reportable_quarter=reportable_quarter,
        filed_at=filed_at,
        cusip=FIXTURE_CUSIPS[ticker],
        ticker=ticker,
        issuer_name=ticker,
        title_of_class="COM",
        shares=10_000.0,
        value_usd=value_usd,
        put_call=None,
        shares_type="SH",
        submission_type="13F-HR",
        is_amendment=False,
        source="fixture",
    )


def apply_post_event_burst(
    frame: pd.DataFrame,
    event_dates: list[date],
    lift_per_session: float = 0.012,
) -> pd.DataFrame:
    burst = frame.copy()
    index = list(burst.index)
    closes = burst["Close"].astype(float).tolist()
    for event_date in event_dates:
        start = next((i for i, ts in enumerate(index) if ts.date() >= event_date), None)
        if start is None:
            continue
        base_start = float(frame["Close"].iloc[start])
        for offset in range(0, 21):
            loc = start + offset
            if loc >= len(closes):
                break
            base = float(frame["Close"].iloc[loc])
            closes[loc] = base + (base_start * lift_per_session * offset)
    burst["Close"] = closes
    burst["Open"] = closes
    burst["High"] = [value + 1 for value in closes]
    burst["Low"] = [value - 1 for value in closes]
    return burst


def aligned_form13f_inputs(*, with_burst: bool = True) -> tuple[list[HoldingPosition], PricePanel]:
    quarters: list[tuple[date, date]] = []
    year, quarter = 2013, 4
    for _ in range(41):
        period = quarter_end(year, quarter)
        quarters.append((period, filing_date(period)))
        if quarter == 4:
            year += 1
            quarter = 1
        else:
            quarter += 1

    holdings: list[HoldingPosition] = []
    event_dates: list[date] = []
    for index, (period, filed) in enumerate(quarters):
        period_text = period.isoformat()
        filed_text = filed.isoformat()
        active_entry = index > 0 and index % 2 == 1
        if active_entry:
            event_dates.append(filed)
        for cik in (*NOTABLE_CIKS, *PASSIVE_CIKS, SINGLE_CIK):
            name = NAMED_NOTABLE_MANAGERS.get(cik) or PASSIVE_INDEX_MANAGERS.get(cik) or cik
            for ticker in ("DDD", "EEE"):
                holdings.append(
                    holding(
                        ticker=ticker,
                        manager_cik=cik,
                        manager_name=name,
                        reportable_quarter=period_text,
                        filed_at=filed_text,
                        accession=f"{cik}-{period_text}-{ticker}",
                    )
                )
        if not active_entry:
            continue
        for ticker in ("AAA", "ZZZ", "YYY"):
            for cik in NOTABLE_CIKS:
                holdings.append(
                    holding(
                        ticker=ticker,
                        manager_cik=cik,
                        manager_name=NAMED_NOTABLE_MANAGERS[cik],
                        reportable_quarter=period_text,
                        filed_at=filed_text,
                        accession=f"{cik}-{period_text}-{ticker}",
                    )
                )
        for cik in (*NOTABLE_CIKS, *PASSIVE_CIKS):
            name = NAMED_NOTABLE_MANAGERS.get(cik) or PASSIVE_INDEX_MANAGERS[cik]
            holdings.append(
                holding(
                    ticker="CCC",
                    manager_cik=cik,
                    manager_name=name,
                    reportable_quarter=period_text,
                    filed_at=filed_text,
                    accession=f"{cik}-{period_text}-CCC",
                )
            )
        holdings.append(
            holding(
                ticker="BBB",
                manager_cik=SINGLE_CIK,
                manager_name=NAMED_NOTABLE_MANAGERS[SINGLE_CIK],
                reportable_quarter=period_text,
                filed_at=filed_text,
                accession=f"{SINGLE_CIK}-{period_text}-BBB",
            )
        )

    start = date(2013, 10, 1)
    sessions = 3200
    spy = history_frame(start, sessions, 100.0, 0.02)
    base = history_frame(start, sessions, 20.0, 0.01)
    cluster_frame = apply_post_event_burst(base, event_dates) if with_burst else base.copy()
    churn_frame = apply_post_event_burst(base, event_dates, lift_per_session=0.008) if with_burst else base.copy()
    frames = {
        "AAA": cluster_frame,
        "ZZZ": cluster_frame.copy(),
        "YYY": cluster_frame.copy(),
        "BBB": base.copy(),
        "CCC": churn_frame,
        "DDD": base.copy(),
        "EEE": base.copy(),
    }

    def _close(frame: pd.DataFrame) -> pd.Series:
        close = pd.to_numeric(frame["Close"], errors="coerce")
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        return close.dropna().sort_index()

    def _volume(frame: pd.DataFrame) -> pd.Series:
        volume = pd.to_numeric(frame["Volume"], errors="coerce")
        volume.index = pd.to_datetime(frame.index).tz_localize(None).normalize()
        return volume.dropna().sort_index()

    panel = PricePanel(
        stock={ticker: _close(frame) for ticker, frame in frames.items()},
        spy=_close(spy),
        volume={ticker: _volume(frame) for ticker, frame in frames.items()},
    )
    return holdings, panel


def evaluate_aligned_fixture(*, with_burst: bool = True) -> dict:
    holdings, panel = aligned_form13f_inputs(with_burst=with_burst)
    return evaluate_form13f_experiment(holdings, panel)
