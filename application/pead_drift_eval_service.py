from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from config.performance import PERFORMANCE_DB_FILE
from domain.evaluation.pead_experiment import (
    HORIZONS,
    INCREMENTAL_HORIZONS,
    MIN_PRIMARY_N_BY_HORIZON,
    MIN_PRIMARY_OOS_N_BY_HORIZON,
    MIN_TRAINING_EVENTS_FOR_FOLD,
    PRIMARY_SURPRISE_ABS_PCT,
    PROTOCOL_VERSION,
    SURPRISE_ABS_CUTS_PCT,
    PeadEventObservation,
    PeadHorizonObservation,
    PeadVerdict,
    decay_curve,
    decide_verdict,
    descriptive_strata,
    evaluate_horizon,
    in_surprise_bucket,
    oos_events,
    protocol_payload,
    surprise_bucket_label,
    surprise_sign,
    verdict_status,
    walk_forward_date_blocks,
)
from domain.research.lifecycle import EXPERIMENT_PEAD
from domain.research.promotion import annotate_calibration_payload
from domain.scoring.pead_shadow import size_bucket_for_market_cap
from storage.repositories.outcome_repository import OutcomeRepository


class PeadDriftEvalService:
    """Shadow-only PEAD eval. Never writes scores or live recommendations."""

    def __init__(
        self,
        outcome_repository: OutcomeRepository | None = None,
        db_path: Path | None = None,
        *,
        events: Sequence[PeadEventObservation] | None = None,
    ) -> None:
        self._db_path = db_path or PERFORMANCE_DB_FILE
        self._outcome_repository = outcome_repository or OutcomeRepository(self._db_path)
        self._provided_events = tuple(events) if events is not None else None

    def build_payload(self) -> dict[str, Any]:
        events, skipped, coverage = self._load_events()
        primary = [
            event
            for event in events
            if in_surprise_bucket(event, PRIMARY_SURPRISE_ABS_PCT)
        ]
        folds = walk_forward_date_blocks([event.event_date for event in primary])
        for fold in folds:
            training_dates = set(fold["training_dates"])
            training_events = sum(event.event_date in training_dates for event in primary)
            if training_events < MIN_TRAINING_EVENTS_FOR_FOLD:
                fold["eligible"] = False
        held_out = oos_events(primary, folds)
        confirmatory = [
            evaluate_horizon(
                primary,
                held_out,
                sessions,
                seed_offset=index * 31,
            )
            for index, sessions in enumerate(INCREMENTAL_HORIZONS)
        ]
        horizon_rows = [
            evaluate_horizon(
                primary,
                held_out,
                sessions,
                seed_offset=100 + index * 31,
            )
            for index, sessions in enumerate(HORIZONS)
            if sessions in {10, *INCREMENTAL_HORIZONS}
        ]
        verdict = decide_verdict(confirmatory)
        bucket_rows = [
            self._bucket_payload(events, abs_cut, held_out_dates={event.event_date for event in held_out})
            for abs_cut in SURPRISE_ABS_CUTS_PCT
        ]
        return annotate_calibration_payload(
            {
                "mode": "shadow",
                "automatic_activation": False,
                "live_score_changes": False,
                "protocol": protocol_payload(),
                "verdict": verdict,
                "status": verdict_status(verdict),
                "summary": self._summary(verdict, confirmatory, primary, held_out, coverage),
                "coverage": coverage,
                "skipped_snapshots": skipped,
                "primary_bucket": surprise_bucket_label(PRIMARY_SURPRISE_ABS_PCT),
                "primary_event_count": len(primary),
                "oos_event_count": len(held_out),
                "walk_forward_folds": [self._fold_payload(fold, primary) for fold in folds],
                "confirmatory_horizons": confirmatory,
                "horizon_tests": horizon_rows,
                "decay_curve": decay_curve(primary),
                "surprise_buckets": bucket_rows,
                "secondary_size": descriptive_strata(
                    primary,
                    20,
                    key=lambda event: event.size_bucket,
                    label="size_bucket",
                ),
                "secondary_sector": descriptive_strata(
                    primary,
                    20,
                    key=lambda event: event.sector or "unknown",
                    label="sector",
                ),
                "secondary_event_date_source": descriptive_strata(
                    primary,
                    20,
                    key=lambda event: event.event_date_source,
                    label="event_date_source",
                ),
                "diagnostic": self._diagnostic(verdict, confirmatory, coverage),
            },
            experiment_id=EXPERIMENT_PEAD,
        )

    def _load_events(self) -> tuple[list[PeadEventObservation], int, dict[str, Any]]:
        if self._provided_events is not None:
            events = sorted(
                self._provided_events,
                key=lambda event: (event.event_date, event.ticker, event.period),
            )
            return events, 0, self._coverage(events, snapshots=len(events), unique_tickers=len({event.ticker for event in events}))

        self._outcome_repository.ensure_schema()
        newest: dict[tuple[str, str, str], tuple[datetime, PeadEventObservation]] = {}
        skipped = 0
        snapshots = 0
        tickers: set[str] = set()
        for row in self._outcome_repository.list_calibration_observations():
            snapshots += 1
            ticker = str(row.get("ticker") or "").upper().strip()
            if ticker:
                tickers.add(ticker)
            parsed = _events_from_row(row)
            if parsed is None:
                skipped += 1
                continue
            created_at = _parse_datetime(row.get("created_at"))
            for event in parsed:
                key = (event.ticker, event.event_date.isoformat(), event.period)
                previous = newest.get(key)
                if previous is None or created_at >= previous[0]:
                    newest[key] = (created_at, event)
        events = [
            item[1]
            for item in sorted(
                newest.values(),
                key=lambda item: (item[1].event_date, item[1].ticker, item[1].period),
            )
        ]
        return events, skipped, self._coverage(events, snapshots=snapshots, unique_tickers=len(tickers))

    def _coverage(
        self,
        events: Sequence[PeadEventObservation],
        *,
        snapshots: int,
        unique_tickers: int,
    ) -> dict[str, Any]:
        complete_by_horizon = {
            sessions: sum(
                1
                for event in events
                if event.horizon(sessions) is not None and event.horizon(sessions).complete
            )
            for sessions in HORIZONS
        }
        sources: dict[str, int] = {}
        for event in events:
            sources[event.event_date_source] = sources.get(event.event_date_source, 0) + 1
        return {
            "snapshots_scanned": snapshots,
            "unique_logged_tickers": unique_tickers,
            "distinct_events": len(events),
            "distinct_event_dates": len({event.event_date for event in events}),
            "complete_events_by_horizon": complete_by_horizon,
            "event_date_sources": sources,
            "price_store_period": "2y",
        }

    def _bucket_payload(
        self,
        events: Sequence[PeadEventObservation],
        abs_cut: float,
        *,
        held_out_dates: set[date],
    ) -> dict[str, Any]:
        scoped = [event for event in events if in_surprise_bucket(event, abs_cut)]
        oos = [event for event in scoped if event.event_date in held_out_dates]
        role = "primary" if abs_cut == PRIMARY_SURPRISE_ABS_PCT else "descriptive_only"
        return {
            "bucket": surprise_bucket_label(abs_cut),
            "abs_cut_pct": abs_cut,
            "role": role,
            "event_count": len(scoped),
            "oos_event_count": len(oos),
            "decay_curve": decay_curve(scoped),
            "by_sign": [
                {
                    "surprise_sign": sign,
                    "role": "descriptive_only",
                    "decay_curve": decay_curve(
                        [event for event in scoped if event.surprise_sign == sign]
                    ),
                }
                for sign in ("beat", "miss")
            ],
        }

    def _fold_payload(
        self,
        fold: dict[str, Any],
        events: Sequence[PeadEventObservation],
    ) -> dict[str, Any]:
        validation_dates = set(fold["validation_dates"])
        training_dates = set(fold["training_dates"])
        return {
            "fold": fold["fold"],
            "training_end": fold["training_end"].isoformat(),
            "validation_start": fold["validation_start"].isoformat(),
            "validation_end": fold["validation_end"].isoformat(),
            "eligible": fold["eligible"],
            "training_events": sum(event.event_date in training_dates for event in events),
            "validation_events": sum(event.event_date in validation_dates for event in events),
            "training_event_dates": len(fold["training_dates"]),
            "validation_event_dates": len(fold["validation_dates"]),
        }

    def _summary(
        self,
        verdict: PeadVerdict,
        confirmatory: Sequence[dict[str, Any]],
        primary: Sequence[PeadEventObservation],
        held_out: Sequence[PeadEventObservation],
        coverage: Mapping[str, Any],
    ) -> str:
        match verdict:
            case "success":
                passed = [row["sessions"] for row in confirmatory if row["passed"]]
                return (
                    f"Primary |surprise| >= {PRIMARY_SURPRISE_ABS_PCT:g}% held-out sample "
                    f"shows surprise-aligned SPY excess continuing at session "
                    f"{', '.join(str(item) for item in passed)}. Shadow only; no live scoring change."
                )
            case "fail":
                return (
                    "Held-out large-surprise sample was large enough to test, but mean "
                    "aligned excess at 20/60 sessions was not distinguishable from zero "
                    "with a non-trivial increment beyond session 3."
                )
            case "data_blocked":
                return (
                    "Abort as data-blocked, not fail-of-hypothesis. Need at least "
                    f"{MIN_PRIMARY_N_BY_HORIZON[20]} complete primary events at 20 sessions "
                    f"(and {MIN_PRIMARY_OOS_N_BY_HORIZON[20]} OOS) or "
                    f"{MIN_PRIMARY_N_BY_HORIZON[60]} at 60 sessions "
                    f"(and {MIN_PRIMARY_OOS_N_BY_HORIZON[60]} OOS). "
                    f"Logged {len(primary)} primary events and {len(held_out)} OOS events "
                    f"from {coverage.get('distinct_events', 0)} distinct earnings events. "
                    "Re-run after scans populate event_drift with complete 10/20/60 windows."
                )

    def _diagnostic(
        self,
        verdict: PeadVerdict,
        confirmatory: Sequence[dict[str, Any]],
        coverage: Mapping[str, Any],
    ) -> dict[str, Any]:
        status = verdict_status(verdict)
        return {
            "title": "PEAD 10/20/60 shadow experiment",
            "status": status,
            "summary": (
                f"{status}. Protocol {PROTOCOL_VERSION} is shadow-only and never "
                "changes live recommendations or scores."
            ),
            "expectation": (
                "For |surprise| >= 5%, surprise-aligned SPY excess at 20 or 60 sessions "
                "should beat zero after 10 bp costs and add at least 0.50 pp beyond the "
                "existing 3-session move on a held-out walk-forward sample."
            ),
            "coverage": coverage,
            "confirmatory_passed": [row["sessions"] for row in confirmatory if row["passed"]],
        }


def _events_from_row(row: Mapping[str, Any]) -> list[PeadEventObservation] | None:
    try:
        snapshot = json.loads(row.get("feature_snapshot_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(snapshot, dict):
        return None
    earnings = snapshot.get("earnings_intelligence")
    if not isinstance(earnings, dict):
        return None
    ticker = str(row.get("ticker") or snapshot.get("ticker") or "").upper().strip()
    if not ticker:
        return None
    event_rows = earnings.get("event_drift")
    if not isinstance(event_rows, list) or not event_rows:
        return None
    events: list[PeadEventObservation] = []
    for payload in event_rows:
        event = _event_from_payload(ticker, payload)
        if event is not None:
            events.append(event)
    return events or None


def _event_from_payload(ticker: str, payload: Any) -> PeadEventObservation | None:
    if not isinstance(payload, dict):
        return None
    surprise = payload.get("surprise_pct")
    if not isinstance(surprise, (int, float)):
        return None
    sign = surprise_sign(float(surprise))
    if sign is None:
        return None
    event_date = _parse_date(payload.get("event_date"))
    if event_date is None:
        return None
    horizon_rows = payload.get("horizons")
    if not isinstance(horizon_rows, list):
        return None
    horizons: list[PeadHorizonObservation] = []
    for row in horizon_rows:
        if not isinstance(row, dict):
            continue
        sessions = row.get("sessions")
        if not isinstance(sessions, int):
            continue
        horizons.append(
            PeadHorizonObservation(
                sessions=sessions,
                complete=bool(row.get("complete")),
                stock_return_pct=_optional_float(row.get("stock_return_pct")),
                market_excess_pct=_optional_float(row.get("market_excess_pct")),
                sector_excess_pct=_optional_float(row.get("sector_excess_pct")),
            )
        )
    if not horizons:
        return None
    market_cap = _optional_float(payload.get("market_cap"))
    return PeadEventObservation(
        ticker=ticker,
        event_date=event_date,
        period=str(payload.get("period") or ""),
        surprise_pct=float(surprise),
        surprise_sign=sign,
        event_date_source=str(payload.get("event_date_source") or "unknown"),
        sector=str(payload.get("sector") or "unknown"),
        size_bucket=str(payload.get("size_bucket") or size_bucket_for_market_cap(market_cap)),
        market_cap=market_cap,
        horizons=tuple(horizons),
    )


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime:
    if value is None or value == "":
        return datetime.min
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min


__all__ = ["PeadDriftEvalService"]
