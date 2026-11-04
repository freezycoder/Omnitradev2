"""Read a saved book against a scan. Research overlap, not a return forecast."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal


PositionRole = Literal["risk", "benefit", "neutral", "unscored"]

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MAX_NAMES = 40
_NAME_LIMIT = 25.0
_SECTOR_LIMIT = 40.0
_WEAK_SCORE = 50.0
_STRONG_SCORE = 80.0
_STRONG_LABEL = "Strong Buy"
_AVOID_LABEL = "Avoid"


@dataclass(frozen=True)
class BookHolding:
    ticker: str
    weight_pct: float


@dataclass(frozen=True)
class BookPosition:
    ticker: str
    weight_pct: float
    sector: str | None
    long_term_score: float | None
    recommendation_label: str | None
    role: PositionRole


@dataclass(frozen=True)
class BookAnalysis:
    holdings: tuple[BookHolding, ...]
    positions: tuple[BookPosition, ...]
    risks: tuple[str, ...]
    benefits: tuple[str, ...]
    cash_pct: float
    largest_weight_pct: float
    summary: str

    def mail_lines(self) -> tuple[str, ...]:
        if not self.holdings:
            return ()
        lines = ["Your book", self.summary]
        if self.risks:
            lines.append("Risks:")
            lines.extend(f"- {item}" for item in self.risks)
        if self.benefits:
            lines.append("Possible benefits:")
            lines.extend(f"- {item}" for item in self.benefits)
        else:
            lines.append("Possible benefits:")
            lines.append("- No saved name is a long-term Strong Buy at 80 or above in this scan.")
        lines.append("Weights are the ones you saved. This is not a forecast of your returns.")
        return tuple(lines)


def parse_holdings(items: Sequence[Mapping[str, Any]]) -> tuple[BookHolding, ...]:
    if len(items) > _MAX_NAMES:
        raise ValueError(f"A book can hold at most {_MAX_NAMES} names.")
    seen: set[str] = set()
    parsed: list[BookHolding] = []
    for item in items:
        ticker = str(item.get("ticker") or "").upper().strip()
        if not _TICKER.fullmatch(ticker):
            raise ValueError(f"Ticker {ticker or '(blank)'} is not a symbol.")
        if ticker in seen:
            raise ValueError(f"{ticker} is listed twice.")
        seen.add(ticker)
        try:
            weight = float(item["weight_pct"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{ticker} needs a weight.") from exc
        if weight <= 0 or weight > 100:
            raise ValueError(f"{ticker} weight must be greater than 0 and at most 100.")
        parsed.append(BookHolding(ticker, round(weight, 2)))
    return tuple(parsed)


def analyze_book(
    holdings: Sequence[BookHolding],
    long_rows: Sequence[Mapping[str, Any]],
    short_rows: Sequence[Mapping[str, Any]] | None = None,
) -> BookAnalysis:
    long_by = {_ticker(row): row for row in long_rows if _ticker(row)}
    short_by = {_ticker(row): row for row in (short_rows or ()) if _ticker(row)}
    risks: list[str] = []
    benefits: list[str] = []
    positions: list[BookPosition] = []
    sector_weights: dict[str, float] = {}
    total = round(sum(holding.weight_pct for holding in holdings), 2)
    cash = round(max(0.0, 100.0 - total), 2) if total <= 100 else 0.0
    if total > 100:
        risks.append(f"Weights add up to {total:.1f}%, which is above 100%.")

    for holding in holdings:
        row = long_by.get(holding.ticker)
        short = short_by.get(holding.ticker)
        if row is None and short is None:
            positions.append(
                BookPosition(holding.ticker, holding.weight_pct, None, None, None, "unscored")
            )
            risks.append(
                f"{holding.ticker} is {holding.weight_pct:.1f}% of the book and is not in the latest scan."
            )
            _note_name_concentration(risks, holding)
            continue
        source = row or short or {}
        sector = str(source.get("sector") or "Unknown")
        score = _as_float(row.get("long_term_score")) if row is not None else None
        label = str(row.get("recommendation_label") or "") if row is not None else None
        sector_weights[sector] = round(sector_weights.get(sector, 0.0) + holding.weight_pct, 2)
        role: PositionRole = "neutral"
        if row is None:
            role = "unscored"
            risks.append(f"{holding.ticker} is in the short-term scan only, so it has no long-term score.")
        elif label == _AVOID_LABEL or (score is not None and score < _WEAK_SCORE):
            role = "risk"
            risks.append(
                f"{holding.ticker} is {holding.weight_pct:.1f}% of the book and scores {_score(score)} ({label or 'unlabeled'})."
            )
        elif label == _STRONG_LABEL and score is not None and score >= _STRONG_SCORE:
            role = "benefit"
            benefits.append(
                f"{holding.ticker} is {holding.weight_pct:.1f}% of the book and is a Strong Buy at {_score(score)}."
            )
        positions.append(BookPosition(holding.ticker, holding.weight_pct, sector, score, label, role))
        _note_name_concentration(risks, holding)

    for sector, weight in sorted(sector_weights.items(), key=lambda item: (-item[1], item[0])):
        if weight >= _SECTOR_LIMIT:
            risks.append(f"{sector} is {weight:.1f}% of the book.")
    if holdings and cash >= 5:
        benefits.append(f"{cash:.1f}% is unallocated, which limits how far one name can move the book.")

    largest = max((holding.weight_pct for holding in holdings), default=0.0)
    count = len(holdings)
    name_word = "name" if count == 1 else "names"
    summary = f"{count} {name_word}. Largest weight {largest:.1f}%. Cash {cash:.1f}%."
    return BookAnalysis(
        holdings=tuple(holdings),
        positions=tuple(positions),
        risks=tuple(risks),
        benefits=tuple(benefits),
        cash_pct=cash,
        largest_weight_pct=largest,
        summary=summary,
    )


def _note_name_concentration(risks: list[str], holding: BookHolding) -> None:
    if holding.weight_pct >= _NAME_LIMIT:
        risks.append(f"{holding.ticker} is {holding.weight_pct:.1f}% of the book.")


def _ticker(row: Mapping[str, Any]) -> str:
    return str(row.get("ticker") or "").upper().strip()


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _score(value: float | None) -> str:
    if value is None:
        return "n/a"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"
