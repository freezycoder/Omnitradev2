from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from config.form144 import (
    CLUSTER_MIN_AFFILIATES,
    CLUSTER_WINDOW_DAYS,
    COVERAGE_START,
    FORM4_LOOKBACK_DAYS,
    FORM144_APPLIED_IMPACT,
    MATCH_RATE_FLOOR,
    MATCH_WINDOW_DAYS,
    MIN_ELIGIBLE_NOTICES,
    MIN_FOLD_NOTICES,
    NESTED_LIFT_EPSILON,
    OPTIONAL_DRIFT_HORIZONS_DAYS,
    PRIMARY_DRIFT_HORIZON_DAYS,
    PRIMARY_SOURCE,
    REQUIRED_POSITIVE_FOLDS,
    WALK_FORWARD_EMBARGO_DAYS,
    WALK_FORWARD_FOLDS,
)
from domain.research.form144_features import (
    detect_clusters,
    eligible_notices,
    ticker_day_intensity,
    with_affiliate_flags,
)
from providers.events.form144_models import (
    Form4Sale,
    ProposedSaleNotice,
    normalize_cik,
    normalize_ticker,
    parse_iso_date,
)


class PricePanel:
    def __init__(self, stock: Mapping[str, pd.Series]) -> None:
        self.stock = {ticker.upper(): series for ticker, series in stock.items()}


def _forward_return(close: pd.Series, as_of: date, sessions: int) -> float | None:
    if close.empty:
        return None
    available = close.loc[close.index >= pd.Timestamp(as_of)]
    if available.empty or sessions >= len(available):
        return None
    start_price = float(available.iloc[0])
    end_price = float(available.iloc[sessions])
    if start_price == 0:
        return None
    return (end_price / start_price - 1.0) * 100.0


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _match_key(issuer_cik: str | None, filer_cik: str | None, ticker: str | None) -> tuple[str, str]:
    issuer = normalize_cik(issuer_cik) or ""
    filer = normalize_cik(filer_cik) or ""
    symbol = normalize_ticker(ticker) or ""
    if issuer and filer:
        return ("issuer_filer", f"{issuer}:{filer}")
    if issuer:
        return ("issuer", issuer)
    return ("ticker", symbol)


def match_notices_to_form4(
    notices: Sequence[ProposedSaleNotice],
    sales: Sequence[Form4Sale],
    *,
    window_days: int = MATCH_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    eligible = eligible_notices(notices)
    by_key: dict[tuple[str, str], list[Form4Sale]] = defaultdict(list)
    for sale in sales:
        if sale.is_derivative:
            continue
        by_key[_match_key(sale.issuer_cik, sale.filer_cik, sale.ticker)].append(sale)

    rows: list[dict[str, Any]] = []
    for notice in eligible:
        intent = parse_iso_date(notice.intent_date)
        filed = parse_iso_date(notice.filed_at)
        if intent is None:
            continue
        start = intent
        end = intent + timedelta(days=window_days)
        candidates: list[Form4Sale] = []
        seen: set[str] = set()
        for key in (
            _match_key(notice.issuer_cik, notice.filer_cik, notice.ticker),
            _match_key(notice.issuer_cik, None, notice.ticker),
            _match_key(None, None, notice.ticker),
        ):
            for sale in by_key.get(key, []):
                sale_id = f"{sale.accession_number}:{sale.transaction_date}:{sale.filer_cik}"
                if sale_id in seen:
                    continue
                seen.add(sale_id)
                event = parse_iso_date(sale.event_date)
                if event is None or event < start or event > end:
                    continue
                candidates.append(sale)
        matched = bool(candidates)
        same_day = False
        lead_days = None
        match_kind = "unmatched"
        matched_accession = None
        if candidates:
            best = min(
                candidates,
                key=lambda sale: abs((parse_iso_date(sale.event_date) or intent) - intent).days,
            )
            event = parse_iso_date(best.event_date) or intent
            lead_days = (event - intent).days
            same_day = lead_days == 0
            match_kind = "same_day" if same_day else "subsequent"
            matched_accession = best.accession_number
        rows.append(
            {
                "accession_number": notice.accession_number,
                "ticker": normalize_ticker(notice.ticker),
                "issuer_cik": normalize_cik(notice.issuer_cik),
                "filer_cik": normalize_cik(notice.filer_cik),
                "filed_at": notice.filed_at,
                "intent_date": intent.isoformat(),
                "proposed_units": notice.proposed_units,
                "prior_3m_units": notice.prior_3m_units,
                "matched": int(matched),
                "same_day_match": int(same_day),
                "subsequent_match": int(matched and not same_day),
                "false_intent": int(not matched),
                "match_kind": match_kind,
                "lead_days": lead_days,
                "matched_form4_accession": matched_accession,
                "filing_lag_days": None if filed is None else (intent - filed).days,
            }
        )
    rows.sort(key=lambda row: (str(row["intent_date"]), str(row["ticker"]), str(row["accession_number"])))
    return rows


def _sales_on_or_before(
    sales: Sequence[Form4Sale],
    *,
    ticker: str,
    issuer_cik: str | None,
    as_of: date,
    lookback_days: int,
) -> list[Form4Sale]:
    start = as_of - timedelta(days=lookback_days - 1)
    issuer = normalize_cik(issuer_cik)
    symbol = normalize_ticker(ticker)
    matched: list[Form4Sale] = []
    for sale in sales:
        event = parse_iso_date(sale.event_date)
        if event is None or event < start or event > as_of:
            continue
        sale_issuer = normalize_cik(sale.issuer_cik)
        sale_ticker = normalize_ticker(sale.ticker)
        if issuer and sale_issuer and issuer == sale_issuer:
            matched.append(sale)
            continue
        if symbol and sale_ticker == symbol:
            matched.append(sale)
    return matched


def _form4_after(
    sales: Sequence[Form4Sale],
    *,
    ticker: str,
    issuer_cik: str | None,
    filer_cik: str | None,
    start: date,
    end: date,
) -> bool:
    want_issuer = normalize_cik(issuer_cik)
    want_filer = normalize_cik(filer_cik)
    want_ticker = normalize_ticker(ticker)
    for sale in sales:
        event = parse_iso_date(sale.event_date)
        if event is None or event < start or event > end:
            continue
        sale_issuer = normalize_cik(sale.issuer_cik)
        sale_filer = normalize_cik(sale.filer_cik)
        sale_ticker = normalize_ticker(sale.ticker)
        if want_issuer and sale_issuer and want_filer and sale_filer:
            if want_issuer == sale_issuer and want_filer == sale_filer:
                return True
            continue
        if want_issuer and sale_issuer and want_issuer == sale_issuer:
            return True
        if want_ticker and sale_ticker == want_ticker:
            return True
    return False


def build_nested_observations(
    notices: Sequence[ProposedSaleNotice],
    sales: Sequence[Form4Sale],
    *,
    panel: PricePanel | None = None,
) -> list[dict[str, Any]]:
    eligible = eligible_notices(notices)
    cluster_keys = {(event.ticker, event.as_of) for event in detect_clusters(eligible)}
    rows: list[dict[str, Any]] = []
    for notice in eligible:
        intent = parse_iso_date(notice.intent_date)
        ticker = normalize_ticker(notice.ticker)
        if intent is None or ticker is None:
            continue
        same_day_sales = _sales_on_or_before(
            sales,
            ticker=ticker,
            issuer_cik=notice.issuer_cik,
            as_of=intent,
            lookback_days=FORM4_LOOKBACK_DAYS,
        )
        form4_intensity = sum(float(sale.shares or 0.0) for sale in same_day_sales)
        form4_count = len(same_day_sales)
        unmatched_units = float(notice.proposed_units or 0.0) if form4_count == 0 else 0.0
        subsequent = _form4_after(
            sales,
            ticker=ticker,
            issuer_cik=notice.issuer_cik,
            filer_cik=notice.filer_cik,
            start=intent + timedelta(days=1),
            end=intent + timedelta(days=MATCH_WINDOW_DAYS),
        )
        row: dict[str, Any] = {
            "accession_number": notice.accession_number,
            "ticker": ticker,
            "intent_date": intent.isoformat(),
            "form4_sell_intensity": form4_intensity,
            "form4_sell_count": form4_count,
            "unmatched_144_intensity": unmatched_units,
            "cluster_144": int((ticker, intent.isoformat()) in cluster_keys),
            "prior_3m_units": float(notice.prior_3m_units or 0.0),
            "subsequent_form4_sale": int(subsequent),
        }
        if panel is not None:
            close = panel.stock.get(ticker, pd.Series(dtype=float))
            for horizon in OPTIONAL_DRIFT_HORIZONS_DAYS:
                ret = _forward_return(close, intent, horizon)
                row[f"stock_return_{horizon}d"] = None if ret is None else round(ret, 4)
        rows.append(row)
    rows.sort(key=lambda item: (str(item["intent_date"]), str(item["ticker"]), str(item["accession_number"])))
    return rows


def _design_matrices(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    y = np.array([float(row["subsequent_form4_sale"]) for row in rows], dtype=float)
    intercept = np.ones(len(rows))
    form4 = np.array([float(row["form4_sell_count"]) for row in rows], dtype=float)
    unmatched = np.array([float(row["unmatched_144_intensity"]) for row in rows], dtype=float)
    cluster = np.array([float(row["cluster_144"]) for row in rows], dtype=float)
    prior = np.array([float(row["prior_3m_units"]) for row in rows], dtype=float)
    baseline = np.column_stack([intercept, form4])
    nested = np.column_stack([intercept, form4, unmatched, cluster, prior])
    return y, baseline, nested


def _predict_mse(y: np.ndarray, x: np.ndarray, beta: np.ndarray) -> float:
    pred = x @ beta
    resid = y - pred
    if resid.size == 0:
        return math.inf
    return float(np.mean(resid ** 2))


def _fit_beta(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return beta


def _walk_forward_folds(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique_dates = sorted({str(row["intent_date"]) for row in rows})
    if len(unique_dates) < 6:
        return []
    initial = max(2, math.ceil(len(unique_dates) * 0.40))
    remaining = unique_dates[initial:]
    if not remaining:
        return []
    block = max(1, math.ceil(len(remaining) / WALK_FORWARD_FOLDS))
    folds: list[dict[str, Any]] = []
    cursor = initial
    for index in range(WALK_FORWARD_FOLDS):
        validation_dates = remaining[index * block : (index + 1) * block]
        if not validation_dates:
            continue
        validation_start = date.fromisoformat(validation_dates[0])
        embargo_cut = (validation_start - timedelta(days=WALK_FORWARD_EMBARGO_DAYS)).isoformat()
        training_dates = {item for item in unique_dates[:cursor] if item <= embargo_cut}
        training_rows = [row for row in rows if str(row["intent_date"]) in training_dates]
        validation_rows = [row for row in rows if str(row["intent_date"]) in set(validation_dates)]
        eligible = (
            len(training_rows) >= MIN_FOLD_NOTICES
            and len(validation_rows) >= max(3, MIN_FOLD_NOTICES // 2)
        )
        lift = False
        mse_base = None
        mse_full = None
        unmatched_coef = None
        if eligible:
            y_train, x_base_train, x_full_train = _design_matrices(training_rows)
            y_val, x_base_val, x_full_val = _design_matrices(validation_rows)
            beta_base = _fit_beta(y_train, x_base_train)
            beta_full = _fit_beta(y_train, x_full_train)
            mse_base = _predict_mse(y_val, x_base_val, beta_base)
            mse_full = _predict_mse(y_val, x_full_val, beta_full)
            unmatched_coef = float(beta_full[2]) if beta_full.size > 2 else None
            lift = bool(
                mse_full + NESTED_LIFT_EPSILON < mse_base
                and unmatched_coef is not None
                and unmatched_coef > 0
            )
        folds.append(
            {
                "fold": index + 1,
                "training_end": unique_dates[cursor - 1],
                "validation_start": validation_dates[0],
                "validation_end": validation_dates[-1],
                "training_notices": len(training_rows),
                "validation_notices": len(validation_rows),
                "eligible": eligible,
                "mse_form4_only": None if mse_base is None else round(mse_base, 6),
                "mse_nested_144": None if mse_full is None else round(mse_full, 6),
                "unmatched_144_coefficient": None
                if unmatched_coef is None
                else round(unmatched_coef, 6),
                "incremental_lift": lift,
            }
        )
        cursor = min(len(unique_dates), cursor + block)
    return folds


def evaluate_form144_experiment(
    notices: Sequence[ProposedSaleNotice],
    sales: Sequence[Form4Sale],
    *,
    panel: PricePanel | None = None,
    form4_store_meta: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    flagged = with_affiliate_flags(notices)
    eligible = [row for row in flagged if row.affiliate_eligible]
    match_rows = match_notices_to_form4(eligible, sales)
    nested_rows = build_nested_observations(eligible, sales, panel=panel)
    intensities = ticker_day_intensity(eligible)
    clusters = detect_clusters(eligible)
    matched = sum(int(row["matched"]) for row in match_rows)
    same_day = sum(int(row["same_day_match"]) for row in match_rows)
    subsequent = sum(int(row["subsequent_match"]) for row in match_rows)
    match_rate = None if not match_rows else matched / len(match_rows)
    false_intent_rate = None if not match_rows else 1.0 - match_rate
    lead_values = [int(row["lead_days"]) for row in match_rows if row["lead_days"] is not None]
    folds = _walk_forward_folds(nested_rows)
    eligible_folds = [fold for fold in folds if fold["eligible"]]
    lift_folds = sum(bool(fold["incremental_lift"]) for fold in eligible_folds)
    thin = len(eligible) < MIN_ELIGIBLE_NOTICES
    match_ok = match_rate is not None and match_rate >= MATCH_RATE_FLOOR
    nested_ok = lift_folds >= REQUIRED_POSITIVE_FOLDS and len(eligible_folds) >= REQUIRED_POSITIVE_FOLDS
    drift_values = [
        float(row[f"stock_return_{PRIMARY_DRIFT_HORIZON_DAYS}d"])
        for row in nested_rows
        if row.get(f"stock_return_{PRIMARY_DRIFT_HORIZON_DAYS}d") is not None
    ]
    drift_mean = _mean(drift_values)
    classification = "not_alpha"
    if not eligible or not match_rows:
        verdict = "FAIL"
        reason = (
            "Structured Form 144 feed is too thin after the affiliate filter "
            f"(eligible notices={len(eligible)}, floor={MIN_ELIGIBLE_NOTICES})."
        )
    elif not match_ok:
        verdict = "FAIL"
        reason = (
            f"Match rate {match_rate:.1%} is below the pre-registered floor "
            f"{MATCH_RATE_FLOOR:.0%}."
        )
    elif thin:
        verdict = "INCONCLUSIVE"
        reason = (
            "Eligible Form 144 notices exist but remain below the pre-registered "
            f"count floor ({len(eligible)} < {MIN_ELIGIBLE_NOTICES})."
        )
    elif nested_ok:
        verdict = "SUCCESS"
        classification = "shadow_calibration"
        reason = (
            f"Match rate {match_rate:.1%} meets the floor and nested 144 intent/clusters "
            f"reduced held-out Form4-sale MSE in {lift_folds}/{len(eligible_folds)} folds."
        )
    else:
        verdict = "SUCCESS_INFRA"
        classification = "infra_conflict_radar"
        reason = (
            f"Match rate {match_rate:.1%} meets the floor, but nested 144 features added "
            "no incremental Form4-sale information vs Form4-only intensity. Keep as "
            "conflict/intent radar only — not an alpha overlay. Human call required."
        )

    return {
        "status": "shadow_research_only",
        "verdict": verdict,
        "classification": classification,
        "alpha_claim": False,
        "jof_car_claim": False,
        "reason": reason,
        "deployment_guard": {
            "automatic_activation": False,
            "applied_impact": FORM144_APPLIED_IMPACT,
            "modeled_impact": 0,
            "live_ranking_changes": False,
            "cannot_flip_live": True,
            "message": (
                "Form 144 is a shadow intent layer. It never writes live "
                "recommendations and is not a JoF-grade CAR claim."
            ),
        },
        "protocol": {
            "primary_source": PRIMARY_SOURCE,
            "coverage_start": COVERAGE_START,
            "cluster_n": CLUSTER_MIN_AFFILIATES,
            "cluster_w_days": CLUSTER_WINDOW_DAYS,
            "match_window_days": MATCH_WINDOW_DAYS,
            "match_rate_floor": MATCH_RATE_FLOOR,
            "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
        },
        "form4_store": {
            "present": bool((form4_store_meta or {}).get("present")),
            "path": (form4_store_meta or {}).get("path"),
            "source": (form4_store_meta or {}).get("source"),
            "sale_count": (form4_store_meta or {}).get("sale_count", len(sales)),
            "notes": (form4_store_meta or {}).get("notes"),
        },
        "data_quality": {
            "notices_in": len(notices),
            "eligible_notices": len(eligible),
            "excluded_notices": len(flagged) - len(eligible),
            "form4_sales": len(sales),
            "tickers": len({row.ticker for row in eligible if row.ticker}),
            "cluster_events": len(clusters),
            "ticker_days": len(intensities),
            "thin_feed": thin,
        },
        "match_study": {
            "notices": len(match_rows),
            "matched": matched,
            "same_day_matches": same_day,
            "subsequent_matches": subsequent,
            "false_intent": len(match_rows) - matched,
            "match_rate": None if match_rate is None else round(match_rate, 4),
            "false_intent_rate": None if false_intent_rate is None else round(false_intent_rate, 4),
            "median_lead_days": None
            if not lead_values
            else int(sorted(lead_values)[len(lead_values) // 2]),
            "floor": MATCH_RATE_FLOOR,
            "floor_met": match_ok,
        },
        "nested_model": {
            "baseline": "form4_sell_count",
            "nested_features": [
                "form4_sell_count",
                "unmatched_144_intensity",
                "cluster_144",
                "prior_3m_units",
            ],
            "target": "subsequent_form4_sale_within_T",
            "walk_forward_folds": folds,
            "eligible_folds": len(eligible_folds),
            "positive_folds": lift_folds,
            "required_positive_folds": REQUIRED_POSITIVE_FOLDS,
            "incremental_lift": nested_ok,
        },
        "optional_drift": {
            "label": "descriptive_only_not_car_not_alpha",
            "horizon_days": PRIMARY_DRIFT_HORIZON_DAYS,
            "mean_stock_return_pct": drift_mean,
            "observations": len(drift_values),
            "used_for_verdict": False,
        },
        "event_rows": match_rows,
        "nested_rows": nested_rows,
        "ticker_day_intensity": [row.to_dict() for row in intensities],
        "clusters": [row.to_dict() for row in clusters],
    }


__all__ = [
    "PricePanel",
    "build_nested_observations",
    "evaluate_form144_experiment",
    "match_notices_to_form4",
]
