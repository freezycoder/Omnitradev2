from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil, floor
from statistics import fmean, median
from typing import Any, Literal, Mapping, Never, Sequence

import pandas as pd

from config.sc13d import (
    BOOTSTRAP_CONFIDENCE_LEVEL,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    DEDUP_CALENDAR_DAYS,
    FORM4_OVERLAP_CALENDAR_DAYS,
    MIN_FOLD_EVENTS,
    MIN_PRIMARY_N,
    MIN_TRAINING_DATES_FOR_FOLD,
    MIN_UNIQUE_EVENT_DATES_FOR_FOLDS,
    POST_WINDOWS,
    PRE_WINDOW,
    PRIMARY_BENCHMARK,
    PRIMARY_WINDOW_KEY,
    PROTOCOL_VERSION,
    REQUIRED_POSITIVE_FOLDS,
    SAMPLE_START,
    SC13D_APPLIED_IMPACT,
    SC13D_MODELED_IMPACT,
    WALK_FORWARD_EMBARGO_DAYS,
    WALK_FORWARD_FOLDS,
    protocol_payload,
)
from domain.research.sc13d_classifier import classify_filing
from providers.events.sc13d_models import (
    ClassifiedSc13dEvent,
    Form4BuyEvent,
    Sc13dFiling,
    parse_iso_date,
)


Sc13dVerdict = Literal["SUCCESS", "FAIL", "INCONCLUSIVE"]


@dataclass(frozen=True)
class PricePanel:
    stock: Mapping[str, pd.Series]
    spy: pd.Series
    sector: Mapping[str, pd.Series]
    ticker_sector: Mapping[str, str]


def close_series(history: pd.DataFrame | pd.Series | None) -> pd.Series:
    if history is None:
        return pd.Series(dtype=float)
    if isinstance(history, pd.Series):
        series = pd.to_numeric(history, errors="coerce")
    else:
        if history.empty or "Close" not in history.columns:
            return pd.Series(dtype=float)
        series = pd.to_numeric(history["Close"], errors="coerce")
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series.dropna().sort_index()


def price_panel_from_frames(
    stock_histories: Mapping[str, pd.DataFrame],
    spy_history: pd.DataFrame,
    *,
    sector_histories: Mapping[str, pd.DataFrame] | None = None,
    ticker_sector: Mapping[str, str] | None = None,
) -> PricePanel:
    return PricePanel(
        stock={ticker.upper(): close_series(frame) for ticker, frame in stock_histories.items()},
        spy=close_series(spy_history),
        sector={symbol.upper(): close_series(frame) for symbol, frame in (sector_histories or {}).items()},
        ticker_sector={
            ticker.upper(): sector.upper() for ticker, sector in (ticker_sector or {}).items()
        },
    )


def _event_index(close: pd.Series, event_date: date) -> int | None:
    if close.empty:
        return None
    target = pd.Timestamp(event_date).normalize()
    position = int(close.index.searchsorted(target, side="left"))
    if position >= len(close):
        return None
    return position


def window_return_pct(close: pd.Series, event_date: date, start: int, end: int) -> float | None:
    t0 = _event_index(close, event_date)
    if t0 is None:
        return None
    start_px_idx = t0 + start - 1
    end_px_idx = t0 + end
    if start_px_idx < 0 or end_px_idx >= len(close) or end_px_idx <= start_px_idx:
        return None
    start_px = float(close.iloc[start_px_idx])
    end_px = float(close.iloc[end_px_idx])
    if start_px <= 0 or end_px <= 0:
        return None
    return (end_px / start_px - 1.0) * 100.0


def _cars_for_close(
    close: pd.Series,
    event_date: date,
) -> dict[str, float | None]:
    payload: dict[str, float | None] = {}
    for key, start, end in (*POST_WINDOWS, PRE_WINDOW):
        payload[key] = (
            None
            if close.empty
            else window_return_pct(close, event_date, start, end)
        )
    return payload


def attach_stake_path(filings: Sequence[Sc13dFiling]) -> list[Sc13dFiling]:
    ordered = sorted(
        filings,
        key=lambda row: (
            row.ticker.upper(),
            row.reporting_cik or "",
            row.filed_at,
            row.accession_number,
        ),
    )
    last_percent: dict[tuple[str, str], float] = {}
    updated: list[Sc13dFiling] = []
    for filing in ordered:
        key = (filing.ticker.upper(), filing.reporting_cik or filing.accession_number)
        prior = last_percent.get(key)
        if prior != filing.prior_percent_of_class:
            payload = filing.to_dict()
            payload["prior_percent_of_class"] = prior
            filing = Sc13dFiling.from_dict(payload)
        if filing.percent_of_class is not None:
            last_percent[key] = filing.percent_of_class
        updated.append(filing)
    return updated


def flag_prior_13g_conversions(
    filings: Sequence[Sc13dFiling],
    thirteen_g: Sequence[Sc13dFiling],
) -> list[Sc13dFiling]:
    priors: dict[tuple[str, str], date] = {}
    for row in thirteen_g:
        filed = parse_iso_date(row.filed_at)
        reporting = row.reporting_cik or ""
        if filed is None or not reporting:
            continue
        key = (row.ticker.upper(), reporting)
        current = priors.get(key)
        if current is None or filed < current:
            priors[key] = filed
    updated: list[Sc13dFiling] = []
    for filing in filings:
        filed = parse_iso_date(filing.filed_at)
        reporting = filing.reporting_cik or ""
        prior = priors.get((filing.ticker.upper(), reporting))
        converted = bool(prior and filed and prior < filed)
        if converted == filing.conversion_prior_13g:
            updated.append(filing)
            continue
        payload = filing.to_dict()
        payload["conversion_prior_13g"] = converted
        payload.pop("conversion_13g_to_13d", None)
        updated.append(Sc13dFiling(**payload))
    return updated


def classify_corpus(filings: Sequence[Sc13dFiling]) -> list[ClassifiedSc13dEvent]:
    return [classify_filing(row) for row in filings]


def _dedup_key_date(event: ClassifiedSc13dEvent) -> date | None:
    return parse_iso_date(event.filed_at)


def dedup_events(events: Sequence[ClassifiedSc13dEvent]) -> list[ClassifiedSc13dEvent]:
    ordered = sorted(
        events,
        key=lambda event: (
            event.ticker,
            event.filing.reporting_cik or "",
            event.filed_at,
            event.accession_number,
        ),
    )
    kept: list[ClassifiedSc13dEvent] = []
    last_kept: dict[tuple[str, str], date] = {}
    for event in ordered:
        filed = _dedup_key_date(event)
        if filed is None:
            continue
        key = (event.ticker, event.filing.reporting_cik or event.accession_number)
        previous = last_kept.get(key)
        if previous is not None and (filed - previous).days <= DEDUP_CALENDAR_DAYS:
            continue
        kept.append(event)
        last_kept[key] = filed
    return kept


def activist_events(events: Sequence[ClassifiedSc13dEvent]) -> list[ClassifiedSc13dEvent]:
    return [
        event
        for event in events
        if event.purpose_class == "activist" and parse_iso_date(event.filed_at) is not None
        and parse_iso_date(event.filed_at) >= SAMPLE_START
    ]


def sample_stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean_pct": None, "median_pct": None, "hit_rate_pct": None}
    return {
        "n": len(values),
        "mean_pct": round(fmean(values), 4),
        "median_pct": round(median(values), 4),
        "hit_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100.0, 1),
    }


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    cluster_keys: Sequence[date] | None = None,
    confidence_level: float = BOOTSTRAP_CONFIDENCE_LEVEL,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
    seed_offset: int = 0,
) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed + seed_offset)
    estimates: list[float] = []
    if cluster_keys is None or len(cluster_keys) != len(values):
        population = list(values)
        for _ in range(iterations):
            sample = [population[rng.randrange(len(population))] for _ in population]
            estimates.append(fmean(sample))
    else:
        grouped: dict[date, list[float]] = {}
        for key, value in zip(cluster_keys, values):
            grouped.setdefault(key, []).append(value)
        dates = list(grouped)
        for _ in range(iterations):
            sampled: list[float] = []
            for _date in range(len(dates)):
                chosen = dates[rng.randrange(len(dates))]
                sampled.extend(grouped[chosen])
            if sampled:
                estimates.append(fmean(sampled))
    if not estimates:
        return None
    estimates.sort()
    alpha = (1 - confidence_level) / 2
    return (_quantile(estimates, alpha), _quantile(estimates, 1 - alpha))


def interval_excludes_zero(interval: tuple[float, float] | None) -> bool:
    if interval is None:
        return False
    low, high = interval
    return high < 0 or low > 0


def walk_forward_date_blocks(event_dates: Sequence[date]) -> list[dict[str, Any]]:
    unique_dates = sorted(set(event_dates))
    if len(unique_dates) < MIN_UNIQUE_EVENT_DATES_FOR_FOLDS:
        return []
    initial_training = max(MIN_TRAINING_DATES_FOR_FOLD, math.ceil(len(unique_dates) * 0.40))
    validation_pool = unique_dates[initial_training:]
    blocks = _split_dates(validation_pool, min(WALK_FORWARD_FOLDS, len(validation_pool)))
    folds: list[dict[str, Any]] = []
    for index, validation_dates in enumerate(blocks, start=1):
        validation_start = validation_dates[0]
        training_end = validation_start - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)
        training_dates = [item for item in unique_dates if item <= training_end]
        folds.append(
            {
                "fold": index,
                "training_end": training_end,
                "validation_start": validation_start,
                "validation_end": validation_dates[-1],
                "validation_dates": tuple(validation_dates),
                "training_dates": tuple(training_dates),
                "eligible": len(training_dates) >= MIN_TRAINING_DATES_FOR_FOLD,
            }
        )
    return folds


def build_event_rows(
    events: Sequence[ClassifiedSc13dEvent],
    panel: PricePanel,
    *,
    form4_buys: Sequence[Form4BuyEvent] | None = None,
) -> list[dict[str, Any]]:
    form4_index = _form4_index(form4_buys or ())
    rows: list[dict[str, Any]] = []
    for event in events:
        filed = parse_iso_date(event.filed_at)
        if filed is None:
            continue
        ticker = event.ticker
        stock = panel.stock.get(ticker, pd.Series(dtype=float))
        sector_symbol = panel.ticker_sector.get(ticker)
        sector = panel.sector.get(sector_symbol or "", pd.Series(dtype=float))
        stock_rets = _cars_for_close(stock, filed)
        spy_rets = _cars_for_close(panel.spy, filed)
        sector_rets = _cars_for_close(sector, filed)
        overlap = _nearby_form4(ticker, filed, form4_index)
        row: dict[str, Any] = {
            "ticker": ticker,
            "filed_at": filed.isoformat(),
            "accession_number": event.accession_number,
            "form": event.filing.form,
            "purpose_class": event.purpose_class,
            "matched_groups": list(event.matched_groups),
            "matched_phrases": list(event.matched_phrases),
            "percent_of_class": event.filing.percent_of_class,
            "prior_percent_of_class": event.filing.prior_percent_of_class,
            "percent_change": (
                None
                if event.filing.percent_of_class is None or event.filing.prior_percent_of_class is None
                else round(event.filing.percent_of_class - event.filing.prior_percent_of_class, 4)
            ),
            "conversion_13g_to_13d": event.filing.conversion_13g_to_13d,
            "sector": sector_symbol,
            "form4_buy_overlap": overlap,
            "mode": "shadow",
            "applied_impact": SC13D_APPLIED_IMPACT,
            "modeled_impact": SC13D_MODELED_IMPACT,
        }
        for key, _start, _end in (*POST_WINDOWS, PRE_WINDOW):
            stock_ret = stock_rets[key]
            spy_ret = spy_rets[key]
            sector_ret = sector_rets[key]
            row[f"stock_{key}"] = None if stock_ret is None else round(stock_ret, 4)
            row[f"spy_{key}"] = None if spy_ret is None else round(spy_ret, 4)
            row[f"sector_{key}"] = None if sector_ret is None else round(sector_ret, 4)
            row[key] = (
                None if stock_ret is None or spy_ret is None else round(stock_ret - spy_ret, 4)
            )
            row[f"sector_excess_{key}"] = (
                None if stock_ret is None or sector_ret is None else round(stock_ret - sector_ret, 4)
            )
        rows.append(row)
    return rows


def _form4_index(events: Sequence[Form4BuyEvent]) -> dict[str, list[date]]:
    index: dict[str, list[date]] = {}
    for event in events:
        filed = parse_iso_date(event.filed_at)
        if filed is None:
            continue
        index.setdefault(event.ticker.upper().strip(), []).append(filed)
    for ticker in index:
        index[ticker] = sorted(set(index[ticker]))
    return index


def _nearby_form4(ticker: str, filed: date, index: Mapping[str, Sequence[date]]) -> bool:
    for other in index.get(ticker.upper(), ()):
        if abs((other - filed).days) <= FORM4_OVERLAP_CALENDAR_DAYS:
            return True
    return False


def _window_values(
    rows: Sequence[Mapping[str, Any]],
    window_key: str,
) -> tuple[list[float], list[date]]:
    values: list[float] = []
    dates: list[date] = []
    for row in rows:
        value = row.get(window_key)
        filed = parse_iso_date(str(row.get("filed_at") or ""))
        if value is None or filed is None:
            continue
        values.append(float(value))
        dates.append(filed)
    return values, dates


def evaluate_window(
    rows: Sequence[Mapping[str, Any]],
    window_key: str,
    *,
    seed_offset: int = 0,
    min_n: int = MIN_FOLD_EVENTS,
) -> dict[str, Any]:
    values, dates = _window_values(rows, window_key)
    interval = bootstrap_mean_interval(values, cluster_keys=dates, seed_offset=seed_offset)
    mean_value = fmean(values) if values else None
    significant = bool(
        len(values) >= min_n
        and mean_value is not None
        and mean_value > 0
        and interval_excludes_zero(interval)
    )
    return {
        "window": window_key,
        "role": "diagnostic_runup" if window_key == PRE_WINDOW[0] else "post_file",
        "testable": len(values) >= min_n,
        **sample_stats(values),
        "bootstrap_ci": _round_interval(interval),
        "ci_excludes_zero": interval_excludes_zero(interval),
        "significant_positive": significant,
    }


def evaluate_fold(
    fold: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validation_dates = {item.isoformat() for item in fold["validation_dates"]}
    validation_rows = [row for row in rows if str(row["filed_at"]) in validation_dates]
    post_windows = [
        evaluate_window(validation_rows, key, seed_offset=fold["fold"] * 31 + index)
        for index, (key, _start, _end) in enumerate(POST_WINDOWS)
    ]
    runup = evaluate_window(
        validation_rows,
        PRE_WINDOW[0],
        seed_offset=fold["fold"] * 31 + 17,
    )
    post_positive = [item for item in post_windows if item["significant_positive"]]
    passed = bool(len(validation_rows) >= MIN_FOLD_EVENTS and post_positive)
    fully_anticipated = bool(
        runup["significant_positive"] and not post_positive and runup["testable"]
    )
    return {
        "fold": fold["fold"],
        "training_end": fold["training_end"].isoformat(),
        "validation_start": fold["validation_start"].isoformat(),
        "validation_end": fold["validation_end"].isoformat(),
        "training_dates": len(fold["training_dates"]),
        "validation_dates": len(fold["validation_dates"]),
        "observations": len(validation_rows),
        "eligible": bool(fold["eligible"] and len(validation_rows) >= MIN_FOLD_EVENTS),
        "post_windows": post_windows,
        "runup": runup,
        "positive_post_windows": [item["window"] for item in post_positive],
        "passed": passed,
        "fully_anticipated": fully_anticipated,
    }


def orthogonality_audit(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    activist = [row for row in rows if row.get("purpose_class") == "activist"]
    overlap = [row for row in activist if row.get("form4_buy_overlap")]
    exclusive = [row for row in activist if not row.get("form4_buy_overlap")]
    return {
        "role": "diagnostic_only",
        "form4_overlap_calendar_days": FORM4_OVERLAP_CALENDAR_DAYS,
        "activist_events": len(activist),
        "overlap_events": len(overlap),
        "overlap_pct": (
            round(len(overlap) / len(activist) * 100.0, 1) if activist else None
        ),
        "car_primary_with_form4": sample_stats(_window_values(overlap, PRIMARY_WINDOW_KEY)[0]),
        "car_primary_13d_only": sample_stats(_window_values(exclusive, PRIMARY_WINDOW_KEY)[0]),
    }


def filter_audit(events: Sequence[ClassifiedSc13dEvent]) -> dict[str, Any]:
    counts = {
        "activist": 0,
        "ambiguous": 0,
        "passive_excluded": 0,
        "financing_excluded": 0,
    }
    for event in events:
        counts[event.purpose_class] += 1
    return {
        "lexicon_version": PROTOCOL_VERSION,
        "total_classified": len(events),
        **counts,
        "primary_used_for_success_gate": "activist",
        "excluded_from_primary": {
            "passive_13g_like": counts["passive_excluded"],
            "pure_financing": counts["financing_excluded"],
        },
        "secondary_only": {"ambiguous": counts["ambiguous"]},
        "filter_document": dict(protocol_payload()["filters"]),
    }


def decide_verdict(
    *,
    activist_n: int,
    fold_results: Sequence[Mapping[str, Any]],
    full_sample_post: Sequence[Mapping[str, Any]],
    runup: Mapping[str, Any],
) -> tuple[Sc13dVerdict, str]:
    eligible = [fold for fold in fold_results if fold.get("eligible")]
    positive_folds = [fold for fold in eligible if fold.get("passed")]
    anticipated_folds = [fold for fold in eligible if fold.get("fully_anticipated")]
    any_post_significant = any(item.get("significant_positive") for item in full_sample_post)

    if activist_n < MIN_PRIMARY_N:
        return "FAIL", (
            f"Sparsity: activist events with a complete {PRIMARY_WINDOW_KEY} window "
            f"are {activist_n}, below the pre-registered N={MIN_PRIMARY_N}."
        )
    if len(eligible) < REQUIRED_POSITIVE_FOLDS:
        return "INCONCLUSIVE", (
            "Held-out sample cannot form the pre-registered walk-forward folds "
            f"({len(eligible)} eligible folds, need {REQUIRED_POSITIVE_FOLDS})."
        )
    if len(positive_folds) >= REQUIRED_POSITIVE_FOLDS:
        return "SUCCESS", (
            f"{len(positive_folds)}/{len(eligible)} walk-forward folds showed significant "
            "positive mean CAR in at least one frozen post-file window after excluding "
            "passive 13G-like and financing filings."
        )
    if runup.get("significant_positive") and not any_post_significant:
        return "FAIL", (
            "Signal is entirely in the (−20,−1) pre-file run-up; no tradeable post-file "
            "window is distinguishable from zero."
        )
    if anticipated_folds and not positive_folds:
        return "FAIL", (
            "Walk-forward folds are fully anticipated: significant run-up without a "
            "significant post-file CAR."
        )
    return "FAIL", (
        "Post-file mean CAR is not significantly positive in "
        f">={REQUIRED_POSITIVE_FOLDS} walk-forward folds after run-up control."
    )


def verdict_status(verdict: Sc13dVerdict) -> str:
    match verdict:
        case "SUCCESS":
            return "Hypothesis supported"
        case "FAIL":
            return "Hypothesis not supported"
        case "INCONCLUSIVE":
            return "Inconclusive"
        case _:
            unreachable: Never = verdict
            raise ValueError(unreachable)


def evaluate_sc13d_experiment(
    filings: Sequence[Sc13dFiling],
    panel: PricePanel,
    *,
    thirteen_g: Sequence[Sc13dFiling] | None = None,
    form4_buys: Sequence[Form4BuyEvent] | None = None,
) -> dict[str, Any]:
    with_path = attach_stake_path(filings)
    with_conversion = flag_prior_13g_conversions(with_path, thirteen_g or ())
    classified = classify_corpus(with_conversion)
    unique_events = dedup_events(classified)
    primary = activist_events(unique_events)
    rows = build_event_rows(primary, panel, form4_buys=form4_buys)
    primary_complete = [row for row in rows if row.get(PRIMARY_WINDOW_KEY) is not None]
    dates = [parse_iso_date(str(row["filed_at"])) for row in primary_complete]
    folds = walk_forward_date_blocks([item for item in dates if item is not None])
    fold_results = [evaluate_fold(fold, primary_complete) for fold in folds]
    post_windows = [
        evaluate_window(primary_complete, key, seed_offset=100 + index, min_n=MIN_PRIMARY_N)
        for index, (key, _start, _end) in enumerate(POST_WINDOWS)
    ]
    runup = evaluate_window(
        primary_complete,
        PRE_WINDOW[0],
        seed_offset=200,
        min_n=MIN_PRIMARY_N,
    )
    ambiguous_rows = build_event_rows(
        [event for event in unique_events if event.purpose_class == "ambiguous"],
        panel,
        form4_buys=form4_buys,
    )
    verdict, reason = decide_verdict(
        activist_n=len(primary_complete),
        fold_results=fold_results,
        full_sample_post=post_windows,
        runup=runup,
    )
    positive_folds = sum(bool(fold["passed"]) for fold in fold_results if fold["eligible"])
    return {
        "status": "shadow_research_only",
        "protocol_version": PROTOCOL_VERSION,
        "verdict": verdict,
        "verdict_status": verdict_status(verdict),
        "reason": reason,
        "deployment_guard": {
            "mode": "shadow",
            "automatic_activation": False,
            "applied_impact": SC13D_APPLIED_IMPACT,
            "modeled_impact": SC13D_MODELED_IMPACT,
            "live_ranking_changes": False,
            "message": (
                "SC 13D activist features are logged shadow-only. They never change "
                "live recommendations."
            ),
        },
        "protocol": protocol_payload(),
        "filters": filter_audit(unique_events),
        "data_quality": {
            "filings_in": len(filings),
            "classified": len(classified),
            "after_dedup": len(unique_events),
            "activist_events": len(primary),
            "activist_complete_primary_window": len(primary_complete),
            "min_primary_n": MIN_PRIMARY_N,
            "tickers": len({row["ticker"] for row in primary_complete}),
            "sample_start": SAMPLE_START.isoformat(),
        },
        "event_study": {
            "benchmark": PRIMARY_BENCHMARK,
            "primary_window": PRIMARY_WINDOW_KEY,
            "post_windows": post_windows,
            "runup": runup,
        },
        "walk_forward_folds": fold_results,
        "positive_folds": positive_folds,
        "orthogonality_vs_form4": orthogonality_audit(rows),
        "secondary_ambiguous": {
            "role": "descriptive_only",
            "n": len(ambiguous_rows),
            "primary_window": evaluate_window(
                ambiguous_rows,
                PRIMARY_WINDOW_KEY,
                seed_offset=300,
                min_n=MIN_FOLD_EVENTS,
            ),
        },
        "event_rows": rows,
    }


def _split_dates(values: Sequence[date], parts: int) -> list[list[date]]:
    if not values or parts <= 0:
        return []
    quotient, remainder = divmod(len(values), parts)
    blocks: list[list[date]] = []
    start = 0
    for index in range(parts):
        width = quotient + (1 if index < remainder else 0)
        blocks.append(list(values[start : start + width]))
        start += width
    return [block for block in blocks if block]


def _quantile(sorted_values: Sequence[float], probability: float) -> float:
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = floor(position)
    upper = ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight)


def _round_interval(interval: tuple[float, float] | None) -> list[float] | None:
    if interval is None:
        return None
    return [round(interval[0], 4), round(interval[1], 4)]


__all__ = [
    "PricePanel",
    "Sc13dVerdict",
    "activist_events",
    "attach_stake_path",
    "build_event_rows",
    "classify_corpus",
    "close_series",
    "decide_verdict",
    "dedup_events",
    "evaluate_sc13d_experiment",
    "evaluate_window",
    "flag_prior_13g_conversions",
    "orthogonality_audit",
    "price_panel_from_frames",
    "verdict_status",
    "walk_forward_date_blocks",
    "window_return_pct",
]
