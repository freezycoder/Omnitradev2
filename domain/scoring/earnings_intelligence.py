from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Sequence

import pandas as pd

from providers.events.sec_edgar_client import SecEventBundle
from providers.news.news_provider import NewsItem


@dataclass(frozen=True)
class EarningsQuarter:
    period: str
    fiscal_year: int | None
    fiscal_quarter: int | None
    actual_eps: float | None
    estimated_eps: float | None
    surprise_abs: float | None
    surprise_pct: float | None
    result: str


@dataclass(frozen=True)
class EarningsIntelligenceView:
    mode: str
    status: str
    score: int | None
    applied_impact: int
    coverage_score: int
    next_earnings_date: str | None
    days_to_earnings: int | None
    event_risk: str
    current_quarter_estimate: float | None
    current_quarter_low: float | None
    current_quarter_high: float | None
    current_quarter_year_ago_eps: float | None
    current_quarter_growth_pct: float | None
    current_quarter_analysts: int | None
    revisions_up_30d: int | None
    revisions_down_30d: int | None
    net_revisions_30d: int | None
    latest_surprise_pct: float | None
    average_surprise_pct: float | None
    beat_rate_pct: float | None
    consecutive_beats: int
    surprise_trend: str
    last_earnings_filing_date: str | None
    post_filing_3d_return_pct: float | None
    guidance_direction: int
    summary: str
    quarters: list[EarningsQuarter] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    as_of_date: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(number) else number


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(parsed) else parsed.date()


def _quarter_from_row(row: dict[str, Any]) -> EarningsQuarter | None:
    period = _parse_date(row.get("period"))
    actual = _number(row.get("actual"))
    estimate = _number(row.get("estimate"))
    surprise_abs = _number(row.get("surprise"))
    surprise_pct = _number(row.get("surprisePercent"))
    if surprise_pct is None and actual is not None and estimate is not None and abs(estimate) >= 0.01:
        surprise_pct = (actual / estimate - 1.0) * 100.0
    if surprise_abs is None and actual is not None and estimate is not None:
        surprise_abs = actual - estimate
    if period is None and actual is None and estimate is None:
        return None
    if surprise_pct is None:
        result = "unresolved"
    elif surprise_pct > 0.1:
        result = "beat"
    elif surprise_pct < -0.1:
        result = "miss"
    else:
        result = "inline"
    return EarningsQuarter(
        period=period.isoformat() if period else str(row.get("period") or ""),
        fiscal_year=_integer(row.get("year")),
        fiscal_quarter=_integer(row.get("quarter")),
        actual_eps=round(actual, 4) if actual is not None else None,
        estimated_eps=round(estimate, 4) if estimate is not None else None,
        surprise_abs=round(surprise_abs, 4) if surprise_abs is not None else None,
        surprise_pct=round(surprise_pct, 2) if surprise_pct is not None else None,
        result=result,
    )


def _earnings_quarters(rows: Sequence[dict[str, Any]]) -> list[EarningsQuarter]:
    quarters = [
        quarter
        for row in rows
        if isinstance(row, dict)
        for quarter in [_quarter_from_row(row)]
        if quarter is not None
    ]
    quarters.sort(key=lambda quarter: quarter.period, reverse=True)
    return quarters[:4]


def _latest_earnings_filing(bundle: SecEventBundle | None) -> str | None:
    if bundle is None:
        return None
    dates = [
        event.filed_at
        for event in bundle.events
        if event.category == "earnings_update" and _parse_date(event.filed_at) is not None
    ]
    return max(dates, default=None)


def _post_filing_return_pct(
    history: pd.DataFrame,
    filing_date: str | None,
    *,
    as_of: date,
    sessions: int = 3,
) -> float | None:
    event_date = _parse_date(filing_date)
    if event_date is None or history.empty or "Close" not in history.columns:
        return None
    close = pd.to_numeric(history["Close"], errors="coerce").dropna().sort_index()
    if close.empty:
        return None
    normalized = close.copy()
    normalized.index = pd.to_datetime(normalized.index).tz_localize(None)
    before = normalized[normalized.index.date < event_date]
    after = normalized[
        (normalized.index.date >= event_date)
        & (normalized.index.date <= as_of)
    ]
    if before.empty or after.empty:
        return None
    target_index = min(sessions - 1, len(after) - 1)
    baseline = float(before.iloc[-1])
    target = float(after.iloc[target_index])
    if baseline <= 0:
        return None
    return (target / baseline - 1.0) * 100.0


def _surprise_trend(quarters: Sequence[EarningsQuarter]) -> str:
    surprises = [
        float(quarter.surprise_pct)
        for quarter in quarters
        if quarter.surprise_pct is not None
    ]
    if len(surprises) < 4:
        return "insufficient"
    recent = sum(surprises[:2]) / 2
    older = sum(surprises[2:4]) / 2
    if recent - older > 1:
        return "improving"
    if recent - older < -1:
        return "weakening"
    return "stable"


def _event_risk(days_to_earnings: int | None) -> str:
    if days_to_earnings is None:
        return "unknown"
    if days_to_earnings <= 3:
        return "high"
    if days_to_earnings <= 7:
        return "elevated"
    if days_to_earnings <= 21:
        return "watch"
    return "normal"


def _status(score: int | None, coverage_score: int) -> str:
    if score is None or coverage_score < 30:
        return "unavailable"
    if score >= 70:
        return "strong"
    if score >= 58:
        return "constructive"
    if score <= 30:
        return "deteriorating"
    if score <= 42:
        return "cautious"
    return "mixed"


def build_earnings_intelligence_view(
    *,
    stock_history: pd.DataFrame,
    earnings_history: Sequence[dict[str, Any]],
    estimate_context: dict[str, Any] | None,
    sec_bundle: SecEventBundle | None = None,
    news_items: Sequence[NewsItem] = (),
    as_of_date: date | None = None,
    warning: str | None = None,
) -> EarningsIntelligenceView:
    context = estimate_context if isinstance(estimate_context, dict) else {}
    if as_of_date is None:
        if not stock_history.empty:
            as_of_date = pd.Timestamp(stock_history.index[-1]).date()
        else:
            as_of_date = datetime.now(UTC).date()

    quarters = _earnings_quarters(earnings_history)
    surprises = [
        float(quarter.surprise_pct)
        for quarter in quarters
        if quarter.surprise_pct is not None
    ]
    resolved_quarters = [
        quarter for quarter in quarters if quarter.result in {"beat", "inline", "miss"}
    ]
    beat_count = sum(quarter.result == "beat" for quarter in resolved_quarters)
    consecutive_beats = 0
    for quarter in resolved_quarters:
        if quarter.result != "beat":
            break
        consecutive_beats += 1

    latest_surprise = surprises[0] if surprises else None
    average_surprise = sum(surprises) / len(surprises) if surprises else None
    beat_rate = beat_count / len(resolved_quarters) * 100 if resolved_quarters else None
    surprise_trend = _surprise_trend(quarters)

    current_quarter = context.get("current_quarter")
    current_quarter = current_quarter if isinstance(current_quarter, dict) else {}
    revisions = context.get("revisions")
    revisions = revisions if isinstance(revisions, dict) else {}
    current_estimate = _number(current_quarter.get("average"))
    estimate_low = _number(current_quarter.get("low"))
    estimate_high = _number(current_quarter.get("high"))
    year_ago_eps = _number(current_quarter.get("year_ago_eps"))
    growth_pct = _number(current_quarter.get("growth_pct"))
    analyst_count = _integer(current_quarter.get("analyst_count"))
    revisions_up = _integer(revisions.get("up_30d"))
    revisions_down = _integer(revisions.get("down_30d"))
    net_revisions = (
        revisions_up - revisions_down
        if revisions_up is not None and revisions_down is not None
        else None
    )

    next_earnings_date = _parse_date(context.get("next_earnings_date"))
    days_to_earnings = (
        (next_earnings_date - as_of_date).days
        if next_earnings_date is not None and next_earnings_date >= as_of_date
        else None
    )
    event_risk = _event_risk(days_to_earnings)
    filing_date = _latest_earnings_filing(sec_bundle)
    post_filing_return = _post_filing_return_pct(
        stock_history,
        filing_date,
        as_of=as_of_date,
    )
    guidance_direction = int(
        _clamp(
            sum(
                item.direction * item.importance
                for item in news_items
                if item.event_type == "guidance"
            ),
            -5,
            5,
        )
    )

    coverage = min(len(surprises), 4) / 4 * 40
    coverage += 20 if current_estimate is not None else 0
    coverage += 20 if revisions_up is not None and revisions_down is not None else 0
    coverage += 10 if next_earnings_date is not None else 0
    coverage += 10 if post_filing_return is not None else 0
    coverage_score = int(round(coverage))

    score_value = 50.0
    if latest_surprise is not None:
        score_value += _clamp(latest_surprise, -10, 10) * 1.2
    if average_surprise is not None:
        score_value += _clamp(average_surprise, -8, 8) * 1.25
    if beat_rate is not None and len(resolved_quarters) >= 2:
        score_value += ((beat_rate - 50) / 50) * 8
    if revisions_up is not None and revisions_down is not None:
        revision_total = revisions_up + revisions_down
        if revision_total > 0:
            score_value += (net_revisions / revision_total) * 10
    if growth_pct is not None:
        score_value += _clamp(growth_pct, -30, 30) / 3
    if post_filing_return is not None:
        score_value += _clamp(post_filing_return, -10, 10) * 0.8
    score = (
        int(round(_clamp(score_value, 0, 100)))
        if coverage_score >= 30
        else None
    )
    status = _status(score, coverage_score)

    evidence: list[str] = []
    if latest_surprise is not None:
        evidence.append(f"Latest reported EPS surprise: {latest_surprise:+.1f}%.")
    if beat_rate is not None:
        evidence.append(
            f"EPS beat rate: {beat_rate:.0f}% across {len(resolved_quarters)} resolved quarters."
        )
    if net_revisions is not None:
        evidence.append(
            f"Thirty-day estimate revisions: {revisions_up} up and {revisions_down} down."
        )
    if growth_pct is not None:
        evidence.append(f"Current-quarter consensus implies {growth_pct:+.1f}% EPS growth.")
    if next_earnings_date is not None:
        evidence.append(
            f"Next scheduled earnings date: {next_earnings_date.isoformat()}"
            + (
                f" ({days_to_earnings} day{'s' if days_to_earnings != 1 else ''})."
                if days_to_earnings is not None
                else "."
            )
        )
    if post_filing_return is not None:
        evidence.append(
            f"Price moved {post_filing_return:+.1f}% over the first three sessions from the latest earnings filing."
        )
    if guidance_direction:
        evidence.append(
            "Recent guidance headlines are "
            + ("constructive." if guidance_direction > 0 else "cautious.")
        )

    warnings: list[str] = []
    if warning:
        warnings.append(warning)
    context_message = context.get("message")
    if isinstance(context_message, str) and context_message.strip():
        warnings.append(context_message.strip())
    if event_risk == "high":
        warnings.append(
            "Earnings are within three days. Gap risk is high, so normal technical levels may not contain the move."
        )
    elif event_risk == "elevated":
        warnings.append(
            "Earnings are within seven days. Treat new entries as event-exposed positions."
        )
    if not quarters:
        warnings.append("Historical EPS surprise data is unavailable.")

    if status == "strong":
        summary = "Earnings execution, estimates, and revisions are strongly supportive."
    elif status == "constructive":
        summary = "Earnings evidence is constructive, though not uniformly strong."
    elif status == "deteriorating":
        summary = "Earnings execution or estimate direction is materially deteriorating."
    elif status == "cautious":
        summary = "Earnings evidence is cautious and raises the burden of proof for an entry."
    elif status == "mixed":
        summary = "Earnings execution and forward expectations are mixed."
    else:
        summary = "Earnings coverage is insufficient for a directional interpretation."
    if event_risk in {"high", "elevated"}:
        summary += " Near-term event risk should be managed separately from the directional score."

    return EarningsIntelligenceView(
        mode="shadow",
        status=status,
        score=score,
        applied_impact=0,
        coverage_score=coverage_score,
        next_earnings_date=next_earnings_date.isoformat() if next_earnings_date else None,
        days_to_earnings=days_to_earnings,
        event_risk=event_risk,
        current_quarter_estimate=round(current_estimate, 4) if current_estimate is not None else None,
        current_quarter_low=round(estimate_low, 4) if estimate_low is not None else None,
        current_quarter_high=round(estimate_high, 4) if estimate_high is not None else None,
        current_quarter_year_ago_eps=round(year_ago_eps, 4) if year_ago_eps is not None else None,
        current_quarter_growth_pct=round(growth_pct, 2) if growth_pct is not None else None,
        current_quarter_analysts=analyst_count,
        revisions_up_30d=revisions_up,
        revisions_down_30d=revisions_down,
        net_revisions_30d=net_revisions,
        latest_surprise_pct=round(latest_surprise, 2) if latest_surprise is not None else None,
        average_surprise_pct=round(average_surprise, 2) if average_surprise is not None else None,
        beat_rate_pct=round(beat_rate, 1) if beat_rate is not None else None,
        consecutive_beats=consecutive_beats,
        surprise_trend=surprise_trend,
        last_earnings_filing_date=filing_date,
        post_filing_3d_return_pct=(
            round(post_filing_return, 2)
            if post_filing_return is not None
            else None
        ),
        guidance_direction=guidance_direction,
        summary=summary,
        quarters=quarters,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
        as_of_date=as_of_date.isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def build_unavailable_earnings_intelligence_view(
    message: str,
) -> EarningsIntelligenceView:
    return EarningsIntelligenceView(
        mode="shadow",
        status="unavailable",
        score=None,
        applied_impact=0,
        coverage_score=0,
        next_earnings_date=None,
        days_to_earnings=None,
        event_risk="unknown",
        current_quarter_estimate=None,
        current_quarter_low=None,
        current_quarter_high=None,
        current_quarter_year_ago_eps=None,
        current_quarter_growth_pct=None,
        current_quarter_analysts=None,
        revisions_up_30d=None,
        revisions_down_30d=None,
        net_revisions_30d=None,
        latest_surprise_pct=None,
        average_surprise_pct=None,
        beat_rate_pct=None,
        consecutive_beats=0,
        surprise_trend="insufficient",
        last_earnings_filing_date=None,
        post_filing_3d_return_pct=None,
        guidance_direction=0,
        summary=message,
        warnings=[message],
        updated_at=datetime.now(UTC).isoformat(),
    )


def earnings_intelligence_view_from_dict(
    payload: dict[str, Any] | None,
) -> EarningsIntelligenceView:
    if not isinstance(payload, dict):
        return build_unavailable_earnings_intelligence_view(
            "The cached snapshot predates earnings intelligence."
        )
    quarter_rows = payload.get("quarters")
    quarters = [
        EarningsQuarter(**row)
        for row in quarter_rows or []
        if isinstance(row, dict)
    ]
    values = dict(payload)
    values["quarters"] = quarters
    return EarningsIntelligenceView(**values)


__all__ = [
    "EarningsIntelligenceView",
    "EarningsQuarter",
    "build_earnings_intelligence_view",
    "build_unavailable_earnings_intelligence_view",
    "earnings_intelligence_view_from_dict",
]
