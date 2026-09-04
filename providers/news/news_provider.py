from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import re

from config.settings import FINNHUB_MAX_HEADLINES, LONG_TERM_NEWS_MAX_IMPACT, SHORT_TERM_NEWS_MAX_IMPACT
from domain.scoring.long_term import LongTermView
from domain.scoring.short_term import ShortTermView


@dataclass
class NewsItem:
    headline: str
    summary: str
    source: str
    url: str
    published_at: str | None
    event_type: str = "other"
    source_quality: str = "other"
    relevance_score: int = 70
    novelty_score: int = 100
    direction: int = 0
    importance: int = 1


@dataclass
class NewsAssessment:
    score: int = 50
    impact_delta: int = 0
    explanation: str = "Recent company news was neutral and did not materially change the model."
    highlights: list[str] = field(default_factory=list)


LONG_TERM_POSITIVE = {
    "partnership": 2,
    "contract": 2,
    "approval": 3,
    "growth": 2,
    "expansion": 2,
    "investment": 2,
    "profit": 2,
    "profitability": 3,
    "raised guidance": 3,
    "beats": 2,
    "launch": 2,
    "acquisition": 2,
}

LONG_TERM_NEGATIVE = {
    "lawsuit": 3,
    "investigation": 3,
    "probe": 3,
    "miss": 2,
    "cuts guidance": 3,
    "decline": 2,
    "layoff": 2,
    "downgrade": 2,
    "recall": 3,
    "debt": 2,
}

SHORT_TERM_POSITIVE = {
    "beats": 3,
    "raised guidance": 4,
    "upgrade": 3,
    "buyback": 2,
    "approval": 4,
    "contract": 3,
    "launch": 2,
    "surge": 3,
    "jump": 2,
    "partnership": 2,
}

SHORT_TERM_NEGATIVE = {
    "miss": 4,
    "cuts guidance": 4,
    "downgrade": 3,
    "offering": 4,
    "lawsuit": 3,
    "investigation": 4,
    "probe": 4,
    "recall": 3,
    "delay": 2,
    "fall": 2,
}

EVENT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("guidance", ("raised guidance", "raises guidance", "cuts guidance", "lowers guidance", "guidance")),
    ("earnings", ("earnings", "quarterly results", "beats estimates", "misses estimates", "revenue")),
    ("mergers_acquisitions", ("acquisition", "acquires", "merger", "takeover", "strategic review")),
    ("regulatory", ("approval", "fda", "regulator", "antitrust", "sec investigation")),
    ("legal", ("lawsuit", "litigation", "probe", "investigation", "settlement")),
    ("capital_allocation", ("buyback", "repurchase", "dividend", "offering", "share sale")),
    ("leadership", ("chief executive", "chief financial", "ceo", "cfo", "director resign")),
    ("contract", ("contract", "partnership", "agreement", "customer win")),
    ("product", ("launch", "recall", "delay", "product")),
    ("analyst_action", ("upgrade", "downgrade", "price target")),
)

POSITIVE_EVENT_PHRASES = {
    "raised guidance": 4,
    "raises guidance": 4,
    "beats estimates": 3,
    "record revenue": 2,
    "approval": 3,
    "buyback": 2,
    "repurchase": 2,
    "contract": 2,
    "customer win": 3,
    "upgrade": 2,
}

NEGATIVE_EVENT_PHRASES = {
    "cuts guidance": 4,
    "lowers guidance": 4,
    "misses estimates": 3,
    "offering": 3,
    "recall": 3,
    "downgrade": 2,
    "investigation": 3,
    "lawsuit": 2,
    "impairment": 3,
    "delay": 2,
}

PRIMARY_NEWS_SOURCES = {
    "business wire",
    "globe newswire",
    "globenewswire",
    "pr newswire",
    "accesswire",
    "sec",
}

ESTABLISHED_NEWS_SOURCES = {
    "associated press",
    "ap",
    "bloomberg",
    "cnbc",
    "financial times",
    "reuters",
    "the wall street journal",
    "wall street journal",
}


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _normalize_timestamp(value: int | float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _headline_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in {"the", "and", "for", "with", "from", "that", "this"}
    }


def _is_near_duplicate(tokens: set[str], previous: list[set[str]]) -> bool:
    if not tokens:
        return False
    for candidate in previous:
        union = tokens | candidate
        if union and len(tokens & candidate) / len(union) >= 0.72:
            return True
    return False


def _event_type(text: str) -> str:
    for label, patterns in EVENT_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return label
    return "other"


def _source_quality(source: str) -> str:
    normalized = source.lower().strip()
    if normalized in PRIMARY_NEWS_SOURCES:
        return "primary_release"
    if normalized in ESTABLISHED_NEWS_SOURCES:
        return "established_reporting"
    return "other"


def _event_direction(text: str) -> tuple[int, int]:
    positive = sum(weight for phrase, weight in POSITIVE_EVENT_PHRASES.items() if phrase in text)
    negative = sum(weight for phrase, weight in NEGATIVE_EVENT_PHRASES.items() if phrase in text)
    net = positive - negative
    if net > 0:
        return 1, min(max(abs(net), 1), 4)
    if net < 0:
        return -1, min(max(abs(net), 1), 4)
    return 0, 1


def _relevance_score(raw_item: dict, text: str, ticker: str, company_name: str) -> int:
    normalized_ticker = ticker.upper().strip()
    related = {
        value.strip().upper()
        for value in str(raw_item.get("related") or "").replace(";", ",").split(",")
        if value.strip()
    }
    if normalized_ticker and normalized_ticker in related:
        return 100
    ticker_pattern = rf"\b{re.escape(normalized_ticker.lower())}\b" if normalized_ticker else ""
    if ticker_pattern and re.search(ticker_pattern, text):
        return 90
    normalized_company = " ".join(company_name.lower().split())
    if normalized_company and normalized_company in text:
        return 85
    return 70


def build_news_items(
    raw_items: list[dict],
    limit: int = FINNHUB_MAX_HEADLINES,
    *,
    ticker: str = "",
    company_name: str = "",
) -> list[NewsItem]:
    normalized: list[NewsItem] = []
    seen: set[str] = set()
    seen_token_sets: list[set[str]] = []
    for item in raw_items:
        headline = (item.get("headline") or "").strip()
        canonical_headline = " ".join(headline.lower().split())
        tokens = _headline_tokens(headline)
        if not headline or canonical_headline in seen or _is_near_duplicate(tokens, seen_token_sets):
            continue
        seen.add(canonical_headline)
        seen_token_sets.append(tokens)
        summary = (item.get("summary") or "").strip()
        source = (item.get("source") or "Finnhub").strip()
        combined_text = f"{headline} {summary}".lower()
        direction, importance = _event_direction(combined_text)
        normalized.append(
            NewsItem(
                headline=headline,
                summary=summary,
                source=source,
                url=(item.get("url") or "").strip(),
                published_at=_normalize_timestamp(item.get("datetime")),
                event_type=_event_type(combined_text),
                source_quality=_source_quality(source),
                relevance_score=_relevance_score(item, combined_text, ticker, company_name),
                novelty_score=100,
                direction=direction,
                importance=importance,
            )
        )
    normalized.sort(key=lambda item: item.published_at or "", reverse=True)
    return normalized[:limit]


def _recency_weight(published_at: str | None, short_term: bool) -> float:
    if not published_at:
        return 1.0
    try:
        parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return 1.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).days, 0)
    if short_term:
        if age_days <= 2:
            return 1.45
        if age_days <= 7:
            return 1.2
        return 0.8
    if age_days <= 7:
        return 1.2
    if age_days <= 14:
        return 1.0
    return 0.75


def _score_item(item: NewsItem, positive_map: dict[str, int], negative_map: dict[str, int], short_term: bool) -> tuple[int, str | None]:
    text = f"{item.headline} {item.summary}".lower()
    positive_points = sum(weight for keyword, weight in positive_map.items() if keyword in text)
    negative_points = sum(weight for keyword, weight in negative_map.items() if keyword in text)
    if positive_points == 0 and negative_points == 0:
        return 0, None

    weighted = int(round((positive_points - negative_points) * _recency_weight(item.published_at, short_term)))
    if weighted > 0:
        return weighted, f"{item.headline} supported the news overlay."
    return weighted, f"{item.headline} added caution to the news overlay."


def _score_news(items: list[NewsItem], positive_map: dict[str, int], negative_map: dict[str, int], max_impact: int, short_term: bool) -> NewsAssessment:
    if not items:
        return NewsAssessment(
            score=50,
            impact_delta=0,
            explanation="No recent Finnhub headlines were available, so news had no material effect on the model.",
            highlights=[],
        )

    net_points = 0
    highlights: list[str] = []
    for item in items:
        contribution, highlight = _score_item(item, positive_map, negative_map, short_term)
        net_points += contribution
        if highlight and len(highlights) < 3:
            highlights.append(highlight)

    score = _clamp(50 + net_points * 4, 0, 100)
    impact_delta = _clamp(int(round((score - 50) / 8)), -max_impact, max_impact)
    if score >= 62:
        explanation = "Recent news flow was constructive and slightly improved the recommendation."
    elif score <= 38:
        explanation = "Recent news flow was negative and modestly reduced the recommendation."
    else:
        explanation = "Recent news flow was mixed, so it only had a limited effect on the recommendation."

    return NewsAssessment(score=score, impact_delta=impact_delta, explanation=explanation, highlights=highlights)


def score_long_term_news(items: list[NewsItem]) -> NewsAssessment:
    return _score_news(items, LONG_TERM_POSITIVE, LONG_TERM_NEGATIVE, LONG_TERM_NEWS_MAX_IMPACT, short_term=False)


def score_short_term_news(items: list[NewsItem]) -> NewsAssessment:
    return _score_news(items, SHORT_TERM_POSITIVE, SHORT_TERM_NEGATIVE, SHORT_TERM_NEWS_MAX_IMPACT, short_term=True)


def apply_long_term_news(view: LongTermView, assessment: NewsAssessment) -> LongTermView:
    score = _clamp(view.score + assessment.impact_delta, 0, 100)
    summary = view.summary if assessment.impact_delta == 0 else f"{view.summary} {assessment.explanation}"
    strengths = list(view.strengths)
    risks = list(view.risks)
    if assessment.impact_delta > 0 and assessment.highlights:
        strengths.extend(highlight for highlight in assessment.highlights if highlight not in strengths)
    if assessment.impact_delta < 0 and assessment.highlights:
        risks.extend(highlight for highlight in assessment.highlights if highlight not in risks)
    return replace(
        view,
        score=score,
        summary=summary,
        strengths=strengths,
        risks=risks,
        news_score=assessment.score,
        news_impact=assessment.impact_delta,
        news_summary=assessment.explanation,
        news_signals=assessment.highlights,
    )


def apply_short_term_news(view: ShortTermView, assessment: NewsAssessment) -> ShortTermView:
    score = _clamp(view.score + assessment.impact_delta, 0, 100)
    reasons = list(view.reasons)
    if assessment.highlights:
        reasons.extend(highlight for highlight in assessment.highlights if highlight not in reasons)
    return replace(
        view,
        score=score,
        reasons=reasons,
        news_score=assessment.score,
        news_impact=assessment.impact_delta,
        news_summary=assessment.explanation,
        news_signals=assessment.highlights,
    )
