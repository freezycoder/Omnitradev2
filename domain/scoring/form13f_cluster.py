from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from config.form13f import (
    CLUSTER_MIN_NOTABLE_MANAGERS,
    FORM13F_APPLIED_IMPACT,
    FORM13F_MAX_MODELED_IMPACT,
    FORM13F_MODE,
    PRIMARY_SOURCE,
    TAXONOMY_VERSION,
)
from domain.research.form13f_features import detect_clusters, detect_streaks, mapped_equity_holdings
from providers.events.form13f_models import HoldingPosition, parse_iso_date


@dataclass(frozen=True)
class Form13FClusterView:
    mode: str
    status: str
    score: int | None
    modeled_impact: int
    applied_impact: int
    coverage_score: int
    primary_source: str
    taxonomy_version: str
    cluster_entry: bool
    cluster_exit: bool
    streak_flag: bool
    notable_count: int
    etf_churn_suspect: bool
    event_date: str | None
    summary: str
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    activation_gate: dict[str, Any] = field(default_factory=dict)
    as_of_date: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _score_from_impact(impact: int) -> int:
    return _clamp(int(round(50 + (impact / FORM13F_MAX_MODELED_IMPACT) * 50)), 0, 100)


def _modeled_impact(*, cluster_entry: bool, cluster_exit: bool, streak_flag: bool, etf_churn: bool) -> int:
    if etf_churn:
        return 0
    impact = 0
    if cluster_entry:
        impact += 3
    if streak_flag:
        impact += 1
    if cluster_exit:
        impact -= 2
    return _clamp(impact, -FORM13F_MAX_MODELED_IMPACT, FORM13F_MAX_MODELED_IMPACT)


def build_form13f_cluster_view(
    *,
    ticker: str,
    holdings: Sequence[HoldingPosition],
    as_of: str | None = None,
) -> Form13FClusterView:
    as_of_date = parse_iso_date(as_of) or datetime.now(UTC).date()
    as_of_holdings = [
        row
        for row in holdings
        if (parsed := parse_iso_date(row.filed_at)) is not None and parsed <= as_of_date
    ]
    clusters = [
        event
        for event in detect_clusters(as_of_holdings)
        if event.ticker.upper() == ticker.upper().strip()
        and (parsed := parse_iso_date(event.event_date)) is not None
        and parsed <= as_of_date
    ]
    streaks = [
        event
        for event in detect_streaks(as_of_holdings)
        if event.ticker.upper() == ticker.upper().strip()
        and (parsed := parse_iso_date(event.event_date)) is not None
        and parsed <= as_of_date
    ]
    scoped = [
        row
        for row in mapped_equity_holdings(as_of_holdings)
        if row.ticker and row.ticker.upper() == ticker.upper().strip()
    ]
    entry = next((event for event in reversed(clusters) if event.direction == "entry"), None)
    exit_event = next((event for event in reversed(clusters) if event.direction == "exit"), None)
    streak = streaks[-1] if streaks else None
    cluster_entry = entry is not None and not entry.etf_churn_suspect
    cluster_exit = exit_event is not None and not exit_event.etf_churn_suspect
    etf_churn = bool(entry and entry.etf_churn_suspect) or bool(exit_event and exit_event.etf_churn_suspect)
    impact = _modeled_impact(
        cluster_entry=cluster_entry,
        cluster_exit=cluster_exit,
        streak_flag=streak is not None,
        etf_churn=etf_churn,
    )
    event_date = None
    if entry is not None:
        event_date = entry.event_date
    elif exit_event is not None:
        event_date = exit_event.event_date
    elif streak is not None:
        event_date = streak.event_date
    evidence: list[str] = []
    if cluster_entry and entry is not None:
        evidence.append(
            f"{entry.notable_count} notable 13F managers newly entered {ticker.upper()} "
            f"in {entry.reportable_quarter}; public as of {entry.event_date}."
        )
    if cluster_exit and exit_event is not None:
        evidence.append(
            f"{exit_event.notable_count} notable 13F managers exited {ticker.upper()} "
            f"in {exit_event.reportable_quarter}; public as of {exit_event.event_date}."
        )
    if streak is not None:
        evidence.append(
            f"Net notable 13F adds persisted for {streak.quarters} consecutive quarters "
            f"through {streak.reportable_quarter}."
        )
    if etf_churn:
        evidence.append("Cluster coincides with passive/index 13F flow and is treated as ETF churn risk.")
    if not scoped:
        status = "unavailable"
        summary = "No mapped 13F holdings are cached for this ticker."
        coverage = 0
    elif not clusters and not streaks:
        status = "available"
        summary = "No frozen K=3 notable cluster or multi-quarter streak is visible after the filing window."
        coverage = 80
    elif etf_churn:
        status = "filtered"
        summary = "A 13F cluster is present but is labeled ETF/index churn and stays shadow-only."
        coverage = 100
    elif cluster_entry:
        status = "constructive"
        summary = "A notable 13F cluster-entry is visible after the public filing lag. It does not change live recommendations."
        coverage = 100
    elif cluster_exit:
        status = "cautious"
        summary = "A notable 13F cluster-exit is visible after the public filing lag. It does not change live recommendations."
        coverage = 100
    else:
        status = "constructive"
        summary = "A notable 13F accumulation streak is visible after the public filing lag. It does not change live recommendations."
        coverage = 100
    return Form13FClusterView(
        mode=FORM13F_MODE,
        status=status,
        score=None if coverage == 0 else _score_from_impact(impact),
        modeled_impact=impact,
        applied_impact=FORM13F_APPLIED_IMPACT,
        coverage_score=coverage,
        primary_source=PRIMARY_SOURCE,
        taxonomy_version=TAXONOMY_VERSION,
        cluster_entry=cluster_entry,
        cluster_exit=cluster_exit,
        streak_flag=streak is not None,
        notable_count=(entry.notable_count if entry is not None else 0),
        etf_churn_suspect=etf_churn,
        event_date=event_date,
        summary=summary,
        evidence=evidence,
        warnings=[] if FORM13F_APPLIED_IMPACT == 0 else ["applied impact must remain zero"],
        activation_gate={
            "status": "collecting_evidence",
            "automatic_activation": False,
            "live_recommendation_changes": False,
            "cluster_k": CLUSTER_MIN_NOTABLE_MANAGERS,
            "taxonomy_version": TAXONOMY_VERSION,
        },
        as_of_date=as_of_date.isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_form13f_cluster_view(message: str) -> Form13FClusterView:
    return Form13FClusterView(
        mode=FORM13F_MODE,
        status="unavailable",
        score=None,
        modeled_impact=0,
        applied_impact=FORM13F_APPLIED_IMPACT,
        coverage_score=0,
        primary_source=PRIMARY_SOURCE,
        taxonomy_version=TAXONOMY_VERSION,
        cluster_entry=False,
        cluster_exit=False,
        streak_flag=False,
        notable_count=0,
        etf_churn_suspect=False,
        event_date=None,
        summary=message,
        warnings=[message],
        activation_gate={
            "status": "collecting_evidence",
            "automatic_activation": False,
            "live_recommendation_changes": False,
        },
        updated_at=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "Form13FClusterView",
    "build_form13f_cluster_view",
    "build_unavailable_form13f_cluster_view",
]
