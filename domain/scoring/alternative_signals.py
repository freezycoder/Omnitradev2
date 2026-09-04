from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.settings import ALTERNATIVE_SIGNALS_MAX_IMPACT, ALTERNATIVE_SIGNALS_MODE
from providers.events.sec_edgar_client import SecEventBundle
from providers.macro.fred_client import FredMacroBundle, FredSeriesSnapshot
from providers.news.news_provider import NewsItem


@dataclass(frozen=True)
class AlternativeSignalComponent:
    key: str
    label: str
    status: str
    score: int | None
    modeled_impact: int
    max_abs_impact: int
    coverage_score: int
    summary: str
    evidence: list[str] = field(default_factory=list)
    updated_at: str | None = None


@dataclass(frozen=True)
class AlternativeSignalView:
    mode: str
    score: int
    modeled_impact: int
    applied_impact: int
    max_abs_impact: int
    coverage_score: int
    status: str
    summary: str
    components: list[AlternativeSignalComponent] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    activation_gate: dict[str, Any] = field(default_factory=dict)
    updated_at: str | None = None


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _score_from_impact(impact: int, max_abs_impact: int) -> int:
    if max_abs_impact <= 0:
        return 50
    return _clamp(int(round(50 + (impact / max_abs_impact) * 50)), 0, 100)


def _sec_component(bundle: SecEventBundle | None) -> AlternativeSignalComponent:
    if bundle is None or bundle.status not in {"available", "partial"}:
        message = bundle.message if bundle else "SEC EDGAR was not queried."
        return AlternativeSignalComponent(
            key="sec_events",
            label="SEC events & insiders",
            status=bundle.status if bundle else "unavailable",
            score=None,
            modeled_impact=0,
            max_abs_impact=6,
            coverage_score=0,
            summary=message or "SEC EDGAR data is unavailable.",
            updated_at=bundle.retrieved_at if bundle else None,
        )

    contributions = [
        event.direction * event.importance
        for event in bundle.events
        if event.direction and event.importance
    ]
    impact = _clamp(sum(contributions), -6, 6)
    evidence = [
        event.summary
        for event in sorted(
            bundle.events,
            key=lambda event: (abs(event.direction * event.importance), event.filed_at),
            reverse=True,
        )
        if event.direction
    ][:4]
    if not bundle.events:
        summary = "No material or ownership filings were found inside the current SEC lookback window."
    elif impact > 0:
        summary = "Recent primary-source filings add constructive event context."
    elif impact < 0:
        summary = "Recent primary-source filings add event or dilution risk."
    else:
        summary = "Recent filings are informational but not directionally decisive."
    return AlternativeSignalComponent(
        key="sec_events",
        label="SEC events & insiders",
        status=bundle.status,
        score=_score_from_impact(impact, 6),
        modeled_impact=impact,
        max_abs_impact=6,
        coverage_score=100,
        summary=summary,
        evidence=evidence,
        updated_at=bundle.retrieved_at,
    )


def _news_component(
    items: list[NewsItem],
    *,
    status: str,
    status_message: str | None,
) -> AlternativeSignalComponent:
    if status == "unavailable":
        return AlternativeSignalComponent(
            key="verified_news",
            label="Classified company news",
            status=status,
            score=None,
            modeled_impact=0,
            max_abs_impact=4,
            coverage_score=0,
            summary=status_message or "Company news is unavailable.",
        )
    if not items:
        return AlternativeSignalComponent(
            key="verified_news",
            label="Classified company news",
            status="available",
            score=50,
            modeled_impact=0,
            max_abs_impact=4,
            coverage_score=100,
            summary="No relevant company headlines were found in the news lookback window.",
        )

    source_weights = {
        "primary_release": 1.0,
        "established_reporting": 1.1,
        "other": 0.75,
    }
    ranked: list[tuple[float, NewsItem]] = []
    for item in items:
        contribution = (
            item.direction
            * item.importance
            * (item.relevance_score / 100)
            * source_weights.get(item.source_quality, 0.75)
        )
        if contribution:
            ranked.append((contribution, item))
    raw_impact = int(round(sum(contribution for contribution, _ in ranked)))
    impact = _clamp(raw_impact, -4, 4)
    evidence = [
        f"{item.event_type.replace('_', ' ').title()}: {item.headline}"
        for contribution, item in sorted(ranked, key=lambda pair: abs(pair[0]), reverse=True)[:4]
    ]
    classified_count = sum(item.event_type != "other" for item in items)
    if impact > 0:
        summary = "Relevant, non-duplicate headlines add constructive event context."
    elif impact < 0:
        summary = "Relevant, non-duplicate headlines add caution."
    else:
        summary = "News events are mixed or non-directional after relevance and source-quality checks."
    return AlternativeSignalComponent(
        key="verified_news",
        label="Classified company news",
        status="available",
        score=_score_from_impact(impact, 4),
        modeled_impact=impact,
        max_abs_impact=4,
        coverage_score=100,
        summary=f"{summary} {classified_count} of {len(items)} headlines received an event classification.",
        evidence=evidence,
        updated_at=max((item.published_at or "" for item in items), default=None) or None,
    )


def _series_value(series: dict[str, FredSeriesSnapshot], key: str) -> FredSeriesSnapshot | None:
    return series.get(key)


def _macro_component(bundle: FredMacroBundle | None) -> AlternativeSignalComponent:
    if bundle is None or bundle.status == "unavailable":
        message = bundle.message if bundle else "FRED was not queried."
        return AlternativeSignalComponent(
            key="macro_regime",
            label="FRED macro regime",
            status="unavailable",
            score=None,
            modeled_impact=0,
            max_abs_impact=4,
            coverage_score=0,
            summary=message or "FRED macro context is unavailable.",
            updated_at=bundle.retrieved_at if bundle else None,
        )

    impact_points = 0
    evidence: list[str] = []
    curve = _series_value(bundle.series, "yield_curve_10y_2y")
    if curve:
        if curve.latest_value < -0.5:
            impact_points -= 2
        elif curve.latest_value < 0:
            impact_points -= 1
        elif curve.latest_value > 0.5:
            impact_points += 1
        evidence.append(f"10Y–2Y spread: {curve.latest_value:.2f} pp.")

    high_yield = _series_value(bundle.series, "high_yield_spread")
    if high_yield:
        if high_yield.latest_value > 5:
            impact_points -= 2
        elif high_yield.latest_value > 4:
            impact_points -= 1
        elif high_yield.latest_value < 3.25:
            impact_points += 1
        if high_yield.change is not None:
            if high_yield.change > 1:
                impact_points -= 2
            elif high_yield.change < -1:
                impact_points += 1
        evidence.append(
            f"High-yield spread: {high_yield.latest_value:.2f} pp"
            + (f" ({high_yield.change:+.2f} over the comparison window)." if high_yield.change is not None else ".")
        )

    conditions = _series_value(bundle.series, "financial_conditions")
    if conditions:
        if conditions.latest_value > 0.5:
            impact_points -= 2
        elif conditions.latest_value > 0:
            impact_points -= 1
        elif conditions.latest_value < 0:
            impact_points += 1
        if conditions.change is not None and conditions.change > 0.25:
            impact_points -= 1
        evidence.append(f"Financial conditions index: {conditions.latest_value:.2f}.")

    fed_funds = _series_value(bundle.series, "fed_funds")
    if fed_funds:
        evidence.append(f"Effective fed funds rate: {fed_funds.latest_value:.2f}%.")

    impact = _clamp(impact_points, -4, 4)
    if impact > 0:
        summary = "The macro backdrop is supportive on the configured regime checks."
    elif impact < 0:
        summary = "The macro backdrop is restrictive or showing stress."
    else:
        summary = "The macro backdrop is balanced on the configured regime checks."
    return AlternativeSignalComponent(
        key="macro_regime",
        label="FRED macro regime",
        status=bundle.status,
        score=_score_from_impact(impact, 4),
        modeled_impact=impact,
        max_abs_impact=4,
        coverage_score=int(round(len(bundle.series) / 4 * 100)),
        summary=summary,
        evidence=evidence,
        updated_at=bundle.retrieved_at,
    )


def build_alternative_signal_view(
    *,
    sec_bundle: SecEventBundle | None,
    news_items: list[NewsItem],
    news_status_message: str | None,
    macro_bundle: FredMacroBundle | None,
) -> AlternativeSignalView:
    news_status = "available"
    lowered_news_status = (news_status_message or "").lower()
    if any(
        token in lowered_news_status
        for token in ("not configured", "unavailable", "rate limit", "http ", "not used", "demo mode")
    ):
        news_status = "unavailable"
    components = [
        _sec_component(sec_bundle),
        _news_component(news_items, status=news_status, status_message=news_status_message),
        _macro_component(macro_bundle),
    ]
    modeled_impact = _clamp(
        sum(component.modeled_impact for component in components),
        -ALTERNATIVE_SIGNALS_MAX_IMPACT,
        ALTERNATIVE_SIGNALS_MAX_IMPACT,
    )
    coverage_weights = {"sec_events": 40, "verified_news": 35, "macro_regime": 25}
    coverage_score = int(
        round(
            sum(
                component.coverage_score * coverage_weights[component.key] / 100
                for component in components
            )
        )
    )
    warnings = [
        component.summary
        for component in components
        if component.status in {"unavailable", "partial", "not_applicable"}
    ]
    evidence = list(
        dict.fromkeys(
            item
            for component in components
            for item in component.evidence
        )
    )[:8]
    if coverage_score < 50:
        status = "limited"
        summary = "Alternative-signal coverage is too limited for interpretation; missing sources are not treated as neutral evidence."
    elif modeled_impact > 0:
        status = "constructive"
        summary = "The shadow event stack is constructive, but it does not change the live recommendation."
    elif modeled_impact < 0:
        status = "cautious"
        summary = "The shadow event stack is cautious, but it does not change the live recommendation."
    else:
        status = "balanced"
        summary = "The shadow event stack is balanced and does not change the live recommendation."

    return AlternativeSignalView(
        mode=ALTERNATIVE_SIGNALS_MODE,
        score=_score_from_impact(modeled_impact, ALTERNATIVE_SIGNALS_MAX_IMPACT),
        modeled_impact=modeled_impact,
        applied_impact=0,
        max_abs_impact=ALTERNATIVE_SIGNALS_MAX_IMPACT,
        coverage_score=coverage_score,
        status=status,
        summary=summary,
        components=components,
        evidence=evidence,
        warnings=warnings,
        activation_gate={
            "status": "collecting_evidence",
            "minimum_resolved_signals": 50,
            "minimum_distinct_signal_dates": 12,
            "required_positive_validation_folds": 2,
            "requires_positive_net_expectancy": True,
            "automatic_activation": False,
        },
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_alternative_signal_view(message: str) -> AlternativeSignalView:
    return AlternativeSignalView(
        mode=ALTERNATIVE_SIGNALS_MODE,
        score=50,
        modeled_impact=0,
        applied_impact=0,
        max_abs_impact=ALTERNATIVE_SIGNALS_MAX_IMPACT,
        coverage_score=0,
        status="unavailable",
        summary=message,
        warnings=[message],
        activation_gate={
            "status": "collecting_evidence",
            "minimum_resolved_signals": 50,
            "minimum_distinct_signal_dates": 12,
            "required_positive_validation_folds": 2,
            "requires_positive_net_expectancy": True,
            "automatic_activation": False,
        },
        updated_at=datetime.now(UTC).isoformat(),
    )


__all__ = [
    "AlternativeSignalComponent",
    "AlternativeSignalView",
    "build_alternative_signal_view",
    "build_unavailable_alternative_signal_view",
]
