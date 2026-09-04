from __future__ import annotations

from dataclasses import dataclass

from domain.scoring.accounting_quality import AccountingQualityView
from domain.scoring.long_term import LongTermView
from domain.scoring.short_term import ShortTermView
from domain.backtest.thresholds import DEFAULT_SCANNER_THRESHOLDS


@dataclass(frozen=True)
class RecommendationRule:
    minimum_score: int
    label: str
    confidence: str
    tone: str


@dataclass
class LongTermRecommendation:
    label: str
    confidence: str
    tone: str
    reasons: list[str]
    risks: list[str]
    thesis: str
    news_effect: str = ""
    accounting_effect: str = ""


@dataclass
class ShortTermRecommendation:
    label: str
    confidence: str
    tone: str
    setup_type: str
    expected_holding_period: str
    entry_idea: str
    stop_loss_idea: str
    target_idea: str
    reasons: list[str]
    invalidation_note: str
    news_effect: str = ""
    accounting_warning: str = ""


@dataclass(frozen=True)
class ScannerRules:
    long_term_min_score: int
    short_term_min_score: int
    min_long_results: int
    min_short_results: int
    long_term_labels: tuple[str, ...]
    short_term_labels: tuple[str, ...]


LONG_TERM_RULES = [
    RecommendationRule(minimum_score=80, label="Strong Buy", confidence="High", tone="positive"),
    RecommendationRule(minimum_score=65, label="Buy", confidence="Moderate", tone="positive"),
    RecommendationRule(minimum_score=45, label="Hold", confidence="Balanced", tone="neutral"),
    RecommendationRule(minimum_score=0, label="Avoid", confidence="High", tone="negative"),
]

SHORT_TERM_RULES = [
    RecommendationRule(minimum_score=75, label="Strong Setup", confidence="High", tone="positive"),
    RecommendationRule(minimum_score=55, label="Watchlist", confidence="Moderate", tone="watch"),
    RecommendationRule(minimum_score=40, label="Neutral", confidence="Balanced", tone="neutral"),
    RecommendationRule(minimum_score=0, label="Avoid", confidence="High", tone="negative"),
]

SCANNER_RULES = ScannerRules(
    long_term_min_score=DEFAULT_SCANNER_THRESHOLDS.min_long_term_scan_score,
    short_term_min_score=DEFAULT_SCANNER_THRESHOLDS.min_short_term_scan_score,
    min_long_results=DEFAULT_SCANNER_THRESHOLDS.min_long_results,
    min_short_results=DEFAULT_SCANNER_THRESHOLDS.min_short_results,
    long_term_labels=("Strong Buy", "Buy"),
    short_term_labels=("Strong Setup", "Watchlist"),
)


def _pick_rule(score: int, rules: list[RecommendationRule]) -> RecommendationRule:
    for rule in rules:
        if score >= rule.minimum_score:
            return rule
    return rules[-1]


def _fill_items(items: list[str], fallback: list[str], count: int) -> list[str]:
    combined: list[str] = []
    for item in items + fallback:
        if item not in combined:
            combined.append(item)
        if len(combined) == count:
            break
    return combined


def _confidence_rank(confidence: str) -> int:
    order = {"Low": 0, "Balanced": 1, "Moderate": 2, "High": 3}
    return order.get(confidence, 1)


def _confidence_from_rank(rank: int) -> str:
    reverse = {0: "Low", 1: "Balanced", 2: "Moderate", 3: "High"}
    return reverse[max(0, min(3, rank))]


def _degrade_confidence(confidence: str, steps: int) -> str:
    return _confidence_from_rank(_confidence_rank(confidence) - steps)


def _cap_rule(rule: RecommendationRule, cap_label: str | None) -> RecommendationRule:
    if not cap_label:
        return rule
    capped = next((candidate for candidate in LONG_TERM_RULES if candidate.label == cap_label), None)
    if capped is None:
        return rule
    if capped.minimum_score <= rule.minimum_score:
        return capped
    return rule


def build_long_term_recommendation(
    view: LongTermView,
    accounting_view: AccountingQualityView | None = None,
) -> LongTermRecommendation:
    rule = _pick_rule(view.score, LONG_TERM_RULES)
    accounting_effect = ""
    if accounting_view is not None:
        rule = _cap_rule(rule, accounting_view.recommendation_cap_label)
        confidence = _degrade_confidence(rule.confidence, accounting_view.confidence_penalty_steps)
        if accounting_view.red_flags or accounting_view.limitations_note:
            accounting_effect = accounting_view.explanation
            if accounting_view.limitations_note:
                accounting_effect = f"{accounting_effect} {accounting_view.limitations_note}".strip()
    else:
        confidence = rule.confidence
    reasons = _fill_items(
        view.strengths + view.news_signals,
        [
            "The long-term score is supported by a blend of trend and business-quality signals.",
            "The current setup is being judged with a multi-year time horizon rather than short-term price noise.",
            "The recommendation reflects the existing long-term score instead of short-term trading conditions.",
        ],
        3,
    )
    risks = _fill_items(
        view.risks + ([accounting_effect] if accounting_effect else []),
        [
            "Any long-term thesis can break if trend support fails or execution slips.",
            "Macro conditions and valuation compression can still pressure returns even when the business stays healthy.",
        ],
        2,
    )
    return LongTermRecommendation(
        label=rule.label,
        confidence=confidence,
        tone=rule.tone,
        reasons=reasons,
        risks=risks,
        thesis=view.thesis,
        news_effect=view.news_summary,
        accounting_effect=accounting_effect,
    )


def build_short_term_recommendation(
    view: ShortTermView,
    accounting_view: AccountingQualityView | None = None,
) -> ShortTermRecommendation:
    rule = _pick_rule(view.score, SHORT_TERM_RULES)
    reasons = _fill_items(
        view.reasons + view.news_signals,
        [
            "The short-term score is based on trend structure, momentum, and confirmation signals.",
            "The setup keeps trading logic separate from any longer-term investing thesis.",
            "Execution quality still depends on confirmation at the proposed entry level.",
        ],
        3,
    )
    return ShortTermRecommendation(
        label=rule.label,
        confidence=rule.confidence,
        tone=rule.tone,
        setup_type=view.setup_type,
        expected_holding_period=view.expected_holding_period,
        entry_idea=view.entry_idea,
        stop_loss_idea=view.stop_loss_idea,
        target_idea=view.target_idea,
        reasons=reasons,
        invalidation_note=view.invalidation_note,
        news_effect=view.news_summary,
        accounting_warning=accounting_view.warning_flag if accounting_view is not None else "",
    )
