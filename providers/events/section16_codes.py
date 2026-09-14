from __future__ import annotations

import re
from typing import Any

from config.section16 import (
    EXCLUDED_CODE_REASONS,
    OPEN_MARKET_CODES,
    TRANSACTION_CODE_MAP,
)


_TENB51_PATTERN = re.compile(
    r"10\s*b\s*5\s*[-\s]*1|rule\s*10b5-1|planned\s+trading\s+arrangement|"
    r"adopted\s+a\s+trading\s+plan",
    re.IGNORECASE,
)
_NEGATED_TENB51_PATTERN = re.compile(
    r"\b(?:not|no|without)\b.{0,40}(?:10\s*b\s*5\s*[-\s]*1|rule\s*10b5-1)|"
    r"(?:10\s*b\s*5\s*[-\s]*1|rule\s*10b5-1).{0,24}\b(?:not|was not)\b",
    re.IGNORECASE,
)


def normalize_transaction_code(value: Any) -> str:
    return str(value or "").strip().upper()


def code_description(code: str) -> str:
    normalized = normalize_transaction_code(code)
    return TRANSACTION_CODE_MAP.get(normalized, "Unknown or undocumented Form 4 transaction code.")


def exclusion_reason(code: str) -> str | None:
    normalized = normalize_transaction_code(code)
    if normalized in OPEN_MARKET_CODES:
        return None
    if not normalized:
        return "missing_transaction_code"
    return EXCLUDED_CODE_REASONS.get(normalized, "undocumented_non_open_market_code")


def is_open_market_code(code: str) -> bool:
    return normalize_transaction_code(code) in OPEN_MARKET_CODES


def footnote_indicates_10b5_1(*texts: str | None) -> bool:
    for text in texts:
        if not text:
            continue
        blob = str(text)
        if _NEGATED_TENB51_PATTERN.search(blob):
            continue
        if _TENB51_PATTERN.search(blob):
            return True
    return False


def truthy_flag(value: Any) -> bool:
    if value is True or value == 1:
        return True
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


__all__ = [
    "code_description",
    "exclusion_reason",
    "footnote_indicates_10b5_1",
    "is_open_market_code",
    "normalize_transaction_code",
    "truthy_flag",
]
