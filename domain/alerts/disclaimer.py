from __future__ import annotations


DECISION_SUPPORT_SENTENCE = "Decision support, not financial advice, and not a broker."
PULLBACK_SENTENCE = (
    "Strategy_v1 still waits for a 0.50% pullback below the signal entry. This is not an order."
)
MAIL_BAR_SENTENCE = "The mail bar is a short-term score of at least 85."
RESEARCH_CTA = "Research this now."

# The decision-support sentence is the sentinel. A body without it is not sendable.
DISCLAIMER_SENTINEL = DECISION_SUPPORT_SENTENCE


class DisclaimerMissing(ValueError):
    """Raised when a rendered body is missing a required sentence."""


def disclaimer_is_present(text: str, *, urgent: bool) -> bool:
    if DISCLAIMER_SENTINEL not in text:
        return False
    if urgent and PULLBACK_SENTENCE not in text:
        return False
    return True


def require_disclaimer(text: str, *, urgent: bool) -> str:
    if not disclaimer_is_present(text, urgent=urgent):
        raise DisclaimerMissing("disclaimer")
    return text


def footer(*, urgent: bool) -> str:
    lines = [DECISION_SUPPORT_SENTENCE]
    if urgent:
        lines.append(PULLBACK_SENTENCE)
    return "\n".join(lines)
