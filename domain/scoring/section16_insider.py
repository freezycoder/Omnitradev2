from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from config.section16 import (
    CLUSTER_MIN_INSIDERS,
    CLUSTER_WINDOW_DAYS,
    FRESHNESS_SLA_DAYS,
    PRIMARY_SOURCE,
    SECTION16_APPLIED_IMPACT,
    SECTION16_MAX_MODELED_IMPACT,
    SECTION16_MODE,
)
from domain.research.section16_features import detect_clusters, detect_streaks, eligible_open_market_rows, net_intensity
from providers.events.section16_models import InsiderTransaction, parse_iso_date


@dataclass(frozen=True)
class Section16InsiderView:
    mode: str
    status: str
    score: int | None
    modeled_impact: int
    applied_impact: int
    coverage_score: int
    primary_source: str
    freshness_source: str
    freshness_days: int | None
    stale_vs_sla: bool
    signed_value_usd: float
    signed_shares: float
    buy_value_usd: float
    sell_value_usd: float
    open_market_count: int
    cluster_flag: bool
    cluster_insider_count: int
    streak_flag: bool
    streak_weeks: int
    overlap_with_edgar_form4: bool
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
    return _clamp(int(round(50 + (impact / SECTION16_MAX_MODELED_IMPACT) * 50)), 0, 100)


def _modeled_impact(signed_value_usd: float, cluster_flag: bool, streak_flag: bool) -> int:
    impact = 0
    if signed_value_usd >= 1_000_000:
        impact += 3
    elif signed_value_usd >= 250_000:
        impact += 2
    elif signed_value_usd > 0:
        impact += 1
    elif signed_value_usd <= -1_000_000:
        impact -= 2
    elif signed_value_usd < 0:
        impact -= 1
    if cluster_flag and signed_value_usd > 0:
        impact += 2
    elif cluster_flag and signed_value_usd < 0:
        impact -= 1
    if streak_flag and signed_value_usd > 0:
        impact += 1
    return _clamp(impact, -SECTION16_MAX_MODELED_IMPACT, SECTION16_MAX_MODELED_IMPACT)


def build_section16_insider_view(
    *,
    ticker: str,
    transactions: Sequence[InsiderTransaction],
    as_of: str | None = None,
    edgar_form4_accessions: Sequence[str] | None = None,
    freshness_source: str | None = None,
) -> Section16InsiderView:
    as_of_date = parse_iso_date(as_of) or datetime.now(UTC).date()
    scoped = [
        row
        for row in eligible_open_market_rows(transactions)
        if row.ticker.upper() == ticker.upper().strip()
        and (parsed := parse_iso_date(row.filed_at)) is not None
        and parsed <= as_of_date
    ]
    signed_value, signed_shares = net_intensity(scoped, ticker=ticker, as_of=as_of_date, lookback_days=20)
    buy_value = sum(float(row.value_usd or 0.0) for row in scoped if row.transaction_code == "P")
    sell_value = sum(float(row.value_usd or 0.0) for row in scoped if row.transaction_code == "S")
    clusters = detect_clusters(scoped, as_of=as_of_date)
    streaks = detect_streaks(scoped, as_of=as_of_date)
    buy_cluster = next((event for event in clusters if event.direction == "P"), None)
    cluster_flag = buy_cluster is not None
    streak = next((event for event in streaks if event.direction == "P"), None)
    streak_flag = streak is not None
    latest_filed = max((parse_iso_date(row.filed_at) for row in scoped), default=None)
    freshness_days = (as_of_date - latest_filed).days if latest_filed else None
    sources = {row.source for row in scoped}
    inferred_source = freshness_source or (
        "mixed"
        if len(sources) > 1
        else next(iter(sources), "unavailable")
    )
    stale = inferred_source == "sec_quarterly_zip" and (
        freshness_days is None or freshness_days > FRESHNESS_SLA_DAYS
    )
    overlap = False
    if edgar_form4_accessions:
        known = {str(item) for item in edgar_form4_accessions}
        overlap = any(row.accession_number in known for row in scoped)

    modeled = _modeled_impact(signed_value, cluster_flag, streak_flag)
    warnings: list[str] = []
    if not scoped:
        warnings.append("No open-market P/S Section-16 rows are available after code and 10b5-1 filters.")
    if stale:
        warnings.append(
            f"Quarterly ZIP freshness is {freshness_days} day(s), which exceeds the "
            f"{FRESHNESS_SLA_DAYS}-day Form-4 SLA; EDGAR XML is required for live freshness."
        )
    if overlap:
        warnings.append("At least one accession already exists in the live SEC EDGAR Form-4 event store.")

    if not scoped:
        status = "unavailable"
        summary = "Section-16 open-market features are unavailable after the pre-registered code filters."
        coverage = 0
        score = None
    else:
        coverage = 100
        score = _score_from_impact(modeled)
        if modeled > 0:
            status = "constructive"
            summary = (
                "Open-market insider buying intensity is constructive on the shadow Section-16 factor. "
                "It does not change the live recommendation."
            )
        elif modeled < 0:
            status = "cautious"
            summary = (
                "Open-market insider selling intensity is cautious on the shadow Section-16 factor. "
                "It does not change the live recommendation."
            )
        else:
            status = "balanced"
            summary = "Open-market Section-16 activity is balanced and does not change the live recommendation."

    evidence: list[str] = []
    if signed_value:
        evidence.append(f"20-day net open-market notional: {signed_value:,.0f} USD.")
    if buy_cluster:
        evidence.append(
            f"Buy cluster: {buy_cluster.insider_count} distinct insiders in {CLUSTER_WINDOW_DAYS}d "
            f"(rule {CLUSTER_MIN_INSIDERS}+/{CLUSTER_WINDOW_DAYS}d)."
        )
    if streak:
        evidence.append(f"Buy streak: {streak.weeks} consecutive weeks, {streak.streak_value_usd:,.0f} USD.")
    evidence.append(f"Primary path: {PRIMARY_SOURCE}. Applied impact is always {SECTION16_APPLIED_IMPACT}.")

    return Section16InsiderView(
        mode=SECTION16_MODE,
        status=status,
        score=score,
        modeled_impact=modeled,
        applied_impact=SECTION16_APPLIED_IMPACT,
        coverage_score=coverage,
        primary_source=PRIMARY_SOURCE,
        freshness_source=inferred_source,
        freshness_days=freshness_days,
        stale_vs_sla=stale,
        signed_value_usd=signed_value,
        signed_shares=signed_shares,
        buy_value_usd=round(buy_value, 2),
        sell_value_usd=round(sell_value, 2),
        open_market_count=len(scoped),
        cluster_flag=cluster_flag,
        cluster_insider_count=buy_cluster.insider_count if buy_cluster else 0,
        streak_flag=streak_flag,
        streak_weeks=streak.weeks if streak else 0,
        overlap_with_edgar_form4=overlap,
        summary=summary,
        evidence=evidence,
        warnings=warnings,
        activation_gate={
            "status": "collecting_evidence",
            "automatic_activation": False,
            "required_positive_validation_folds": 2,
            "overlap_enrichment_threshold_pct": 70.0,
        },
        as_of_date=as_of_date.isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_section16_insider_view(message: str) -> Section16InsiderView:
    return Section16InsiderView(
        mode=SECTION16_MODE,
        status="unavailable",
        score=None,
        modeled_impact=0,
        applied_impact=SECTION16_APPLIED_IMPACT,
        coverage_score=0,
        primary_source=PRIMARY_SOURCE,
        freshness_source="unavailable",
        freshness_days=None,
        stale_vs_sla=False,
        signed_value_usd=0.0,
        signed_shares=0.0,
        buy_value_usd=0.0,
        sell_value_usd=0.0,
        open_market_count=0,
        cluster_flag=False,
        cluster_insider_count=0,
        streak_flag=False,
        streak_weeks=0,
        overlap_with_edgar_form4=False,
        summary=message,
        warnings=[message],
        activation_gate={
            "status": "collecting_evidence",
            "automatic_activation": False,
            "required_positive_validation_folds": 2,
            "overlap_enrichment_threshold_pct": 70.0,
        },
        updated_at=datetime.now(UTC).isoformat(),
    )


def section16_insider_view_from_dict(payload: dict[str, Any] | None) -> Section16InsiderView:
    if not isinstance(payload, dict):
        return build_unavailable_section16_insider_view(
            "The cached snapshot predates Section-16 shadow features."
        )
    try:
        return Section16InsiderView(**payload)
    except TypeError:
        return build_unavailable_section16_insider_view(
            "The cached Section-16 snapshot is incomplete."
        )


__all__ = [
    "Section16InsiderView",
    "build_section16_insider_view",
    "build_unavailable_section16_insider_view",
    "section16_insider_view_from_dict",
]
