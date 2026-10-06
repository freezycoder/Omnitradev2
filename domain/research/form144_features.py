from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Sequence

from config.form144 import (
    CLUSTER_MIN_AFFILIATES,
    CLUSTER_WINDOW_DAYS,
    COVERAGE_START,
    FORM144_APPLIED_IMPACT,
    FORM144_MODELED_IMPACT,
)
from providers.events.form144_models import (
    Form144ClusterEvent,
    ProposedSaleNotice,
    TickerDayIntensity,
    normalize_cik,
    normalize_ticker,
    parse_iso_date,
)


def classify_affiliate(notice: ProposedSaleNotice) -> tuple[bool, str]:
    filer = normalize_cik(notice.filer_cik)
    issuer = normalize_cik(notice.issuer_cik)
    filed = parse_iso_date(notice.filed_at)
    coverage = parse_iso_date(COVERAGE_START)
    if filed is None:
        return False, "missing_filed_at"
    if coverage is not None and filed < coverage:
        return False, "pre_electronic_mandate"
    if filer is None:
        return False, "missing_filer_cik"
    if issuer is None:
        return False, "missing_issuer_cik"
    if filer == issuer:
        return False, "issuer_self_filing"
    if not normalize_ticker(notice.ticker):
        return False, "missing_ticker"
    return True, "affiliate_filer_cik"


def with_affiliate_flags(
    notices: Sequence[ProposedSaleNotice],
) -> list[ProposedSaleNotice]:
    flagged: list[ProposedSaleNotice] = []
    for notice in notices:
        eligible, reason = classify_affiliate(notice)
        flagged.append(
            ProposedSaleNotice(
                **{
                    **notice.to_dict(),
                    "affiliate_eligible": eligible,
                    "affiliate_reason": reason,
                }
            )
        )
    return flagged


def eligible_notices(notices: Sequence[ProposedSaleNotice]) -> list[ProposedSaleNotice]:
    return [row for row in with_affiliate_flags(notices) if row.affiliate_eligible]


def ticker_day_intensity(
    notices: Sequence[ProposedSaleNotice],
) -> list[TickerDayIntensity]:
    grouped: dict[tuple[str, str], list[ProposedSaleNotice]] = defaultdict(list)
    for notice in eligible_notices(notices):
        ticker = normalize_ticker(notice.ticker)
        as_of = notice.intent_date[:10]
        if ticker is None or not as_of:
            continue
        grouped[(ticker, as_of)].append(notice)

    cluster_keys = {
        (event.ticker, event.as_of) for event in detect_clusters(notices)
    }
    rows: list[TickerDayIntensity] = []
    for (ticker, as_of), group in grouped.items():
        filers = tuple(
            sorted({normalize_cik(row.filer_cik) or "" for row in group if normalize_cik(row.filer_cik)})
        )
        rows.append(
            TickerDayIntensity(
                ticker=ticker,
                as_of=as_of,
                notice_count=len(group),
                affiliate_count=len(filers),
                proposed_units=round(sum(float(row.proposed_units or 0.0) for row in group), 4),
                cluster=(ticker, as_of) in cluster_keys,
                filer_ciks=filers,
                accession_numbers=tuple(sorted({row.accession_number for row in group})),
            )
        )
    rows.sort(key=lambda row: (row.as_of, row.ticker))
    return rows


def detect_clusters(
    notices: Sequence[ProposedSaleNotice],
    *,
    min_affiliates: int = CLUSTER_MIN_AFFILIATES,
    window_days: int = CLUSTER_WINDOW_DAYS,
) -> list[Form144ClusterEvent]:
    """Frozen cluster: ≥N distinct affiliate filers on the same ticker in W days."""

    rows = eligible_notices(notices)
    by_ticker: dict[str, list[ProposedSaleNotice]] = defaultdict(list)
    for notice in rows:
        ticker = normalize_ticker(notice.ticker)
        if ticker is None:
            continue
        by_ticker[ticker].append(notice)

    events: list[Form144ClusterEvent] = []
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    for ticker, group in by_ticker.items():
        dated = [
            (parse_iso_date(notice.intent_date), notice)
            for notice in group
            if parse_iso_date(notice.intent_date) is not None
        ]
        dated.sort(key=lambda item: item[0] or parse_iso_date("9999-12-31"))
        for as_of, _anchor in dated:
            if as_of is None:
                continue
            window_start = as_of - timedelta(days=window_days - 1)
            window_rows = [
                notice
                for filed, notice in dated
                if filed is not None and window_start <= filed <= as_of
            ]
            filers = tuple(
                sorted(
                    {
                        normalize_cik(notice.filer_cik) or ""
                        for notice in window_rows
                        if normalize_cik(notice.filer_cik)
                    }
                )
            )
            if len(filers) < min_affiliates:
                continue
            key = (ticker, as_of.isoformat(), filers)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                Form144ClusterEvent(
                    ticker=ticker,
                    as_of=as_of.isoformat(),
                    window_start=window_start.isoformat(),
                    affiliate_count=len(filers),
                    filer_ciks=filers,
                    proposed_units=round(
                        sum(float(notice.proposed_units or 0.0) for notice in window_rows),
                        4,
                    ),
                    accession_numbers=tuple(
                        sorted({notice.accession_number for notice in window_rows})
                    ),
                )
            )
    events.sort(key=lambda event: (event.as_of, event.ticker))
    return events


def shadow_guard() -> dict[str, int | bool | str]:
    return {
        "mode": "shadow",
        "applied_impact": FORM144_APPLIED_IMPACT,
        "modeled_impact": FORM144_MODELED_IMPACT,
        "live_recommendation_changes": False,
        "treat_all_144s_as_bearish": False,
    }


__all__ = [
    "classify_affiliate",
    "detect_clusters",
    "eligible_notices",
    "shadow_guard",
    "ticker_day_intensity",
    "with_affiliate_flags",
]
