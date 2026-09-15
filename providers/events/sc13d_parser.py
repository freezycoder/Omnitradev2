from __future__ import annotations

import html
import re
from typing import Iterable

from config.sc13d import CONVERSION_PHRASES
from providers.events.sc13d_models import ParsedSc13dDocument


_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
_ITEM_4_RE = re.compile(
    r"item\s*4\s*[\.:]?\s*(?:purpose of (?:the )?transaction)?(?P<body>.*?)(?=item\s*5\s*[\.:]|$)",
    re.IGNORECASE | re.DOTALL,
)
_ITEM_5_RE = re.compile(
    r"item\s*5\s*[\.:]?\s*(?:interest in securities of the issuer)?(?P<body>.*?)(?=item\s*6\s*[\.:]|$)",
    re.IGNORECASE | re.DOTALL,
)
_PERCENT_PATTERNS = (
    re.compile(
        r"percent of class represented by amount in row(?:\s*\(\d+\))?[^\d%]{0,40}(?P<pct>\d{1,2}(?:\.\d+)?)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"percent of class[^\d%]{0,60}(?P<pct>\d{1,2}(?:\.\d+)?)\s*%",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"(?P<pct>\d{1,2}(?:\.\d+)?)\s*%\s+of\s+(?:the\s+)?(?:outstanding\s+)?(?:shares|class|common)",
        re.IGNORECASE,
    ),
    re.compile(
        r"beneficially owns?\s+[^\d%]{0,80}(?P<pct>\d{1,2}(?:\.\d+)?)\s*%",
        re.IGNORECASE,
    ),
)
_REPORTING_CIK_RE = re.compile(
    r"(?:irs|i\.r\.s\.)?\s*(?:identification nos?\.? of above persons|cik)[^\d]{0,40}(?P<cik>\d{6,10})",
    re.IGNORECASE,
)
_NAKED_CIK_RE = re.compile(r"\bCIK\s*[#:No\.]*\s*0*(?P<cik>\d{1,10})\b", re.IGNORECASE)
_REPORTING_NAME_RE = re.compile(
    r"name of reporting persons?\s*(?P<name>[A-Za-z0-9][^\n|]{2,80})",
    re.IGNORECASE,
)
_ISSUER_NAME_RE = re.compile(
    r"name of issuer\s*(?P<name>[A-Za-z0-9][^\n|]{2,80})",
    re.IGNORECASE,
)


def plain_text(raw: str | bytes | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)
    text = html.unescape(text)
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\xa0", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_search_text(text: str) -> str:
    collapsed = plain_text(text).lower()
    collapsed = collapsed.replace("–", "-").replace("—", "-")
    collapsed = collapsed.replace("-", " ")
    return _WHITESPACE_RE.sub(" ", collapsed).strip()


def extract_section(text: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    return _WHITESPACE_RE.sub(" ", match.group("body")).strip()


def parse_percent_of_class(text: str) -> float | None:
    search_space = extract_section(text, _ITEM_5_RE) or text
    for pattern in _PERCENT_PATTERNS:
        match = pattern.search(search_space)
        if not match:
            continue
        try:
            value = float(match.group("pct"))
        except (TypeError, ValueError):
            continue
        if 0 < value <= 100:
            return value
    return None


def _first_group(text: str, pattern: re.Pattern[str], name: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    value = match.group(name).strip(" .;,:")
    return value or None


def _cik(text: str) -> str | None:
    match = _REPORTING_CIK_RE.search(text) or _NAKED_CIK_RE.search(text)
    if not match:
        return None
    return str(int(match.group("cik"))).zfill(10)


_NEGATION_RE = re.compile(r"\b(?:not|without|no)\b")


def phrase_is_negated(haystack: str, start: int, *, window: int = 48) -> bool:
    prefix = haystack[max(0, start - window) : start]
    return bool(_NEGATION_RE.search(prefix))


def matched_literal_phrases(
    text: str,
    phrases: Iterable[str],
    *,
    ignore_negated: bool = False,
) -> tuple[str, ...]:
    haystack = normalize_search_text(text)
    hits: list[str] = []
    for phrase in phrases:
        needle = normalize_search_text(phrase)
        if not needle:
            continue
        start = 0
        while True:
            index = haystack.find(needle, start)
            if index < 0:
                break
            if ignore_negated and phrase_is_negated(haystack, index):
                start = index + 1
                continue
            hits.append(phrase)
            break
    return tuple(hits)


def conversion_phrases_in(text: str, phrases: Iterable[str] = CONVERSION_PHRASES) -> tuple[str, ...]:
    return matched_literal_phrases(text, phrases, ignore_negated=True)


def parse_sc13d_document(raw: str | bytes | None) -> ParsedSc13dDocument:
    text = plain_text(raw)
    purpose = extract_section(text, _ITEM_4_RE)
    conversion_hits = conversion_phrases_in(text)
    return ParsedSc13dDocument(
        purpose_text=purpose or text[:4000],
        percent_of_class=parse_percent_of_class(text),
        reporting_cik=_cik(text),
        reporting_name=_first_group(text, _REPORTING_NAME_RE, "name"),
        issuer_name=_first_group(text, _ISSUER_NAME_RE, "name"),
        conversion_text_flag=bool(conversion_hits),
        matched_conversion_phrases=conversion_hits,
    )


__all__ = [
    "conversion_phrases_in",
    "extract_section",
    "matched_literal_phrases",
    "normalize_search_text",
    "parse_percent_of_class",
    "parse_sc13d_document",
    "phrase_is_negated",
    "plain_text",
]
