from __future__ import annotations

from typing import Literal, Never

from config.sc13d import (
    AMBIGUOUS_PHRASES,
    FINANCING_PHRASES,
    LEXICON_VERSION,
    PASSIVE_PHRASES,
    all_primary_phrases,
    lexicon_groups,
)
from providers.events.sc13d_models import ClassifiedSc13dEvent, PurposeClass, Sc13dFiling
from providers.events.sc13d_parser import matched_literal_phrases


MatchGroup = Literal[
    "hostile",
    "board_seat",
    "activist_purpose",
    "ambiguous",
    "passive_exclude",
    "financing_exclude",
    "conversion",
]


def matched_phrases(text: str, phrases: tuple[str, ...], *, ignore_negated: bool = False) -> tuple[str, ...]:
    return matched_literal_phrases(text, phrases, ignore_negated=ignore_negated)


def lexicon_hits(text: str) -> dict[str, tuple[str, ...]]:
    hits: dict[str, tuple[str, ...]] = {}
    for group, phrases in lexicon_groups():
        ignore_negated = group in {"hostile", "board_seat", "activist_purpose"}
        hits[group] = matched_phrases(text, phrases, ignore_negated=ignore_negated)
    return hits


def classify_purpose(text: str) -> tuple[PurposeClass, tuple[str, ...], tuple[str, ...], str | None]:
    hits = lexicon_hits(text)
    primary_groups = tuple(
        group
        for group in ("hostile", "board_seat", "activist_purpose")
        if hits[group]
    )
    primary_phrases = tuple(phrase for group in primary_groups for phrase in hits[group])
    if primary_phrases:
        return "activist", primary_groups, primary_phrases, None
    if hits["financing_exclude"]:
        return (
            "financing_excluded",
            ("financing_exclude",),
            hits["financing_exclude"],
            "pure_financing_disclosure",
        )
    if hits["passive_exclude"]:
        return (
            "passive_excluded",
            ("passive_exclude",),
            hits["passive_exclude"],
            "passive_13g_like_language",
        )
    ambiguous = hits["ambiguous"]
    if ambiguous:
        return "ambiguous", ("ambiguous",), ambiguous, None
    return "ambiguous", (), (), None


def classify_filing(filing: Sc13dFiling) -> ClassifiedSc13dEvent:
    purpose_class, groups, phrases, reason = classify_purpose(filing.purpose_text)
    conversion_hits = lexicon_hits(filing.purpose_text + " " + filing.raw_excerpt).get("conversion", ())
    matched_groups = groups + (("conversion",) if (filing.conversion_13g_to_13d or conversion_hits) else ())
    matched_phrases_out = phrases + conversion_hits
    return ClassifiedSc13dEvent(
        filing=filing,
        purpose_class=purpose_class,
        matched_groups=tuple(dict.fromkeys(matched_groups)),
        matched_phrases=tuple(dict.fromkeys(matched_phrases_out)),
        exclude_reason=reason,
    )


def purpose_class_label(purpose_class: PurposeClass) -> str:
    match purpose_class:
        case "activist":
            return "activist"
        case "ambiguous":
            return "ambiguous"
        case "passive_excluded":
            return "passive_excluded"
        case "financing_excluded":
            return "financing_excluded"
        case _:
            unreachable: Never = purpose_class
            raise ValueError(unreachable)


def lexicon_is_frozen() -> dict[str, object]:
    return {
        "lexicon_version": LEXICON_VERSION,
        "primary_phrase_count": len(all_primary_phrases()),
        "passive_phrase_count": len(PASSIVE_PHRASES),
        "financing_phrase_count": len(FINANCING_PHRASES),
        "ambiguous_phrase_count": len(AMBIGUOUS_PHRASES),
    }


__all__ = [
    "MatchGroup",
    "classify_filing",
    "classify_purpose",
    "lexicon_hits",
    "lexicon_is_frozen",
    "matched_phrases",
    "purpose_class_label",
]
