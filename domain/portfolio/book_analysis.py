"""Read a saved book against a scan. Research overlap, not a return forecast."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from domain.portfolio.known_etfs import KnownEtf, canonical_ticker, resolve_known_etf


PositionRole = Literal["risk", "benefit", "neutral", "unscored"]
Coverage = Literal["scan", "portfolio", "fund", "none"]
Posture = Literal["maintain", "trim", "rebuild", "empty"]
StrategyKind = Literal["keep", "trim", "review", "research", "cash"]

_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_MAX_NAMES = 40
# Matches PortfolioEngineService.MAX_SINGLE_NAME_WEIGHT. Domain stays free of that import.
_NAME_LIMIT = 20.0
_THEME_LIMIT = 15.0
_US_SLEEVE_REVIEW = 45.0
_SECTOR_LIMIT = 40.0
_WEAK_SCORE = 50.0
_STRONG_SCORE = 80.0
_SHENANIGAN_REVIEW = 70.0
_STRONG_LABEL = "Strong Buy"
_AVOID_LABEL = "Avoid"
_POSTURE_LABEL = {
    "maintain": "Maintain",
    "trim": "Trim, then keep the core",
    "rebuild": "Do not treat this mix as the core",
    "empty": "Add holdings",
}


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
    shenanigan_risk: float | None = None
    asset_kind: str = "stock"
    coverage: Coverage = "scan"


@dataclass(frozen=True)
class BookStrategy:
    kind: StrategyKind
    ticker: str | None
    title: str
    detail: str


@dataclass(frozen=True)
class BookAnalysis:
    holdings: tuple[BookHolding, ...]
    positions: tuple[BookPosition, ...]
    risks: tuple[str, ...]
    benefits: tuple[str, ...]
    cash_pct: float
    largest_weight_pct: float
    summary: str
    posture: Posture
    posture_label: str
    posture_reason: str
    risk_score: int
    strategies: tuple[BookStrategy, ...]

    def mail_lines(self) -> tuple[str, ...]:
        if not self.holdings:
            return ()
        lines = [
            "Your portfolio",
            self.summary,
            f"Risk score {self.risk_score} of 100. {self.posture_label}. {self.posture_reason}",
        ]
        if self.strategies:
            lines.append("Next research steps:")
            lines.extend(f"- {item.title}" for item in self.strategies[:4])
        lines.append("This is a research posture from the scan and the 20% name cap. It is not a forecast of your returns.")
        return tuple(lines)


def parse_holdings(items: Sequence[Mapping[str, Any]]) -> tuple[BookHolding, ...]:
    if len(items) > _MAX_NAMES:
        raise ValueError(f"A book can hold at most {_MAX_NAMES} names.")
    seen: set[str] = set()
    parsed: list[BookHolding] = []
    for item in items:
        ticker = canonical_ticker(str(item.get("ticker") or ""))
        if resolve_known_etf(ticker) is None and not _TICKER.fullmatch(ticker):
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
            fund = resolve_known_etf(holding.ticker)
            if fund is None:
                positions.append(
                    BookPosition(
                        holding.ticker,
                        holding.weight_pct,
                        None,
                        None,
                        None,
                        "unscored",
                        shenanigan_risk=None,
                        coverage="none",
                    )
                )
                risks.append(
                    f"{holding.ticker} is {holding.weight_pct:.1f}% of the book and has no live price data to score."
                )
                _note_name_concentration(risks, holding)
            else:
                positions.append(_etf_position(holding, fund))
                benefits.append(
                    f"{fund.ticker} is {holding.weight_pct:.1f}% and is {fund.name}. The stock scan does not score this fund."
                )
                _note_etf_weight(risks, holding, fund)
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
        shenanigan = _as_float(row.get("shenanigan_risk_score")) if row is not None else None
        if shenanigan is not None and shenanigan >= _SHENANIGAN_REVIEW and holding.weight_pct >= 5:
            risks.append(
                f"{holding.ticker} accounting shenanigan risk is {_score(shenanigan)}. Treat that weight as review, not as a core hold."
            )
        coverage: Coverage = "portfolio" if row is not None and row.get("scored_for_portfolio") else "scan"
        positions.append(
            BookPosition(
                holding.ticker,
                holding.weight_pct,
                sector,
                score,
                label,
                role,
                shenanigan_risk=shenanigan,
                coverage=coverage,
            )
        )
        _note_name_concentration(risks, holding)

    for sector, weight in sorted(sector_weights.items(), key=lambda item: (-item[1], item[0])):
        if weight >= _SECTOR_LIMIT:
            risks.append(f"{sector} is {weight:.1f}% of the book.")
    us_equity = _us_equity_weight(positions)
    if us_equity >= _US_SLEEVE_REVIEW:
        risks.append(
            f"About {us_equity:.0f}% of the book is US large-cap equity. "
            "An S&P 500 fund repeats the US stocks already inside the all-world fund."
        )
    if holdings and cash >= 5:
        benefits.append(f"{cash:.1f}% is unallocated, which limits how far one name can move the book.")

    largest = max((holding.weight_pct for holding in holdings), default=0.0)
    count = len(holdings)
    name_word = "name" if count == 1 else "names"
    summary = f"{count} {name_word}. Largest weight {largest:.1f}%. Cash {cash:.1f}%."
    plan = _plan(holdings, tuple(positions), sector_weights, long_by, cash, total)
    return BookAnalysis(
        holdings=tuple(holdings),
        positions=tuple(positions),
        risks=tuple(risks),
        benefits=tuple(benefits),
        cash_pct=cash,
        largest_weight_pct=largest,
        summary=summary,
        posture=plan.posture,
        posture_label=plan.label,
        posture_reason=plan.reason,
        risk_score=plan.risk_score,
        strategies=plan.strategies,
    )


@dataclass(frozen=True)
class _Plan:
    posture: Posture
    label: str
    reason: str
    risk_score: int
    strategies: tuple[BookStrategy, ...]


def _plan(
    holdings: Sequence[BookHolding],
    positions: tuple[BookPosition, ...],
    sector_weights: dict[str, float],
    long_by: dict[str, Mapping[str, Any]],
    cash: float,
    total: float,
) -> _Plan:
    if not holdings:
        return _Plan("empty", _POSTURE_LABEL["empty"], "Save ticker weights to read this portfolio.", 0, ())
    weak = round(sum(item.weight_pct for item in positions if item.role == "risk"), 2)
    unscored = round(sum(item.weight_pct for item in positions if item.role == "unscored"), 2)
    risk_score = _risk_score(holdings, sector_weights, weak, unscored, total)
    if risk_score >= 55 or weak + unscored >= 40:
        posture: Posture = "rebuild"
        reason = (
            "Too much weight sits above the 20% name cap, in a weak score, or outside the scan "
            "to treat this mix as the core."
        )
    elif (
        risk_score >= 25
        or any(_stock_over_cap(item) for item in holdings)
        or weak >= 10
        or any(_theme_over_cap(item) for item in holdings)
        or _us_equity_weight(positions) >= 55
    ):
        posture = "trim"
        reason = (
            "Keep the Strong Buys that sit inside the 20% cap, and reduce the weight above that cap "
            "or on a weak score."
        )
    else:
        posture = "maintain"
        reason = (
            "The saved weights sit inside the 20% name cap, and the scan does not mark a large weak sleeve. "
            "Maintaining this mix is the research posture."
        )
    return _Plan(posture, _POSTURE_LABEL[posture], reason, risk_score, _strategies(positions, long_by, cash, posture))


def _risk_score(
    holdings: Sequence[BookHolding],
    sector_weights: dict[str, float],
    weak: float,
    unscored: float,
    total: float,
) -> int:
    score = 0.0
    for holding in holdings:
        fund = resolve_known_etf(holding.ticker)
        if fund is not None and fund.kind == "broad_equity":
            continue
        if fund is not None and fund.kind == "thematic" and holding.weight_pct > _THEME_LIMIT:
            score += min(30.0, (holding.weight_pct - _THEME_LIMIT) * 1.5)
            continue
        if fund is not None and fund.kind == "us_large_cap" and holding.weight_pct > 40:
            score += min(25.0, holding.weight_pct - 40)
            continue
        if fund is not None:
            continue
        if holding.weight_pct > _NAME_LIMIT:
            score += min(30.0, (holding.weight_pct - _NAME_LIMIT) * 1.5)
    for weight in sector_weights.values():
        if weight > _SECTOR_LIMIT:
            score += min(25.0, weight - _SECTOR_LIMIT)
    score += weak * 0.7
    score += unscored * 0.45
    if total > 100:
        score += min(20.0, total - 100)
    return int(min(100, round(score)))


def _strategies(
    positions: tuple[BookPosition, ...],
    long_by: dict[str, Mapping[str, Any]],
    cash: float,
    posture: Posture,
) -> tuple[BookStrategy, ...]:
    steps: list[BookStrategy] = []
    held = {item.ticker for item in positions}
    for position in sorted(positions, key=lambda item: item.weight_pct, reverse=True):
        if position.asset_kind == "theme_etf" and position.weight_pct > _THEME_LIMIT:
            extra = round(position.weight_pct - _THEME_LIMIT, 1)
            steps.append(
                BookStrategy(
                    "trim",
                    position.ticker,
                    f"Trim {position.ticker} from {position.weight_pct:.1f}% toward {_THEME_LIMIT:.0f}%.",
                    "A quantum computing fund is a narrow theme. Keep it as a satellite, not as a core holding.",
                )
            )
            continue
        if position.asset_kind != "stock" or position.weight_pct <= _NAME_LIMIT:
            continue
        if position.weight_pct > _NAME_LIMIT:
            extra = round(position.weight_pct - _NAME_LIMIT, 1)
            steps.append(
                BookStrategy(
                    "trim",
                    position.ticker,
                    f"Trim {position.ticker} from {position.weight_pct:.1f}% toward 20%.",
                    f"The extra {extra:.1f}% would sit in cash until another name qualifies under the same cap.",
                )
            )
    for position in positions:
        shaky = position.role == "risk" or (
            position.shenanigan_risk is not None and position.shenanigan_risk >= _SHENANIGAN_REVIEW
        )
        if position.asset_kind == "broad_etf":
            steps.append(
                BookStrategy(
                    "keep",
                    position.ticker,
                    f"Keep {position.ticker} at {position.weight_pct:.1f}% as the diversified core.",
                    "This is a broad UCITS fund. Its weight is not a single-stock concentration.",
                )
            )
            continue
        if position.asset_kind == "us_etf" and any(item.asset_kind == "broad_etf" for item in positions):
            steps.append(
                BookStrategy(
                    "review",
                    position.ticker,
                    f"Review {position.ticker} at {position.weight_pct:.1f}% beside the all-world fund.",
                    "The S&P 500 fund repeats US large caps that the all-world fund already holds.",
                )
            )
            continue
        if position.asset_kind == "us_etf":
            steps.append(
                BookStrategy(
                    "keep",
                    position.ticker,
                    f"Keep {position.ticker} at {position.weight_pct:.1f}% as the US sleeve.",
                    "This fund is the S&P 500. It is a market sleeve, not a single stock.",
                )
            )
            continue
        if position.asset_kind == "theme_etf" and position.weight_pct <= _THEME_LIMIT:
            steps.append(
                BookStrategy(
                    "keep",
                    position.ticker,
                    f"Keep {position.ticker} at {position.weight_pct:.1f}% as a satellite.",
                    "The quantum fund is a theme sleeve. It is not a substitute for the broad fund.",
                )
            )
            continue
        if shaky and position.weight_pct >= 5:
            steps.append(
                BookStrategy(
                    "review",
                    position.ticker,
                    f"Review {position.ticker} before keeping {position.weight_pct:.1f}%.",
                    "The long-term scan marks a weak score, an Avoid label, or a high accounting-risk reading.",
                )
            )
        elif position.role == "benefit" and position.weight_pct <= _NAME_LIMIT:
            steps.append(
                BookStrategy(
                    "keep",
                    position.ticker,
                    f"Keep {position.ticker} at {position.weight_pct:.1f}%.",
                    f"It is a Strong Buy at {_score(position.long_term_score)} and inside the 20% cap.",
                )
            )
    candidates = [
        row
        for ticker, row in long_by.items()
        if ticker not in held
        and str(row.get("recommendation_label") or "") == _STRONG_LABEL
        and (_as_float(row.get("long_term_score")) or 0) >= _STRONG_SCORE
    ]
    candidates.sort(key=lambda row: _as_float(row.get("long_term_score")) or 0, reverse=True)
    for row in candidates[:3]:
        ticker = _ticker(row)
        steps.append(
            BookStrategy(
                "research",
                ticker,
                f"Research {ticker} as a possible next name.",
                (
                    f"Long-term score {_score(_as_float(row.get('long_term_score')))}, Strong Buy, not in this portfolio. "
                    "A new name still has to be triggered, with positive expectancy and a size above zero, "
                    "before the strategy engine would give it weight."
                ),
            )
        )
    if cash >= 15 and posture != "rebuild":
        steps.append(
            BookStrategy(
                "cash",
                None,
                f"Leave {cash:.1f}% unallocated.",
                "The strategy engine also holds cash when too few names fit under the 20% cap.",
            )
        )
    return tuple(steps[:6])


def _etf_position(holding: BookHolding, fund: KnownEtf) -> BookPosition:
    role: PositionRole = "benefit" if fund.kind == "broad_equity" else "neutral"
    sector = {
        "broad_equity": "All-world equity",
        "us_large_cap": "US large cap",
        "thematic": "Quantum computing",
    }[fund.kind]
    return BookPosition(
        holding.ticker,
        holding.weight_pct,
        sector,
        None,
        fund.name,
        role,
        shenanigan_risk=None,
        asset_kind={"broad_equity": "broad_etf", "us_large_cap": "us_etf", "thematic": "theme_etf"}[fund.kind],
        coverage="fund",
    )


def _note_etf_weight(risks: list[str], holding: BookHolding, fund: KnownEtf) -> None:
    if fund.kind == "thematic" and holding.weight_pct > _THEME_LIMIT:
        risks.append(
            f"{fund.ticker} is {holding.weight_pct:.1f}% of the book. "
            f"A theme fund above {_THEME_LIMIT:.0f}% is a satellite that has become large."
        )


def _us_equity_weight(positions: Sequence[BookPosition]) -> float:
    total = 0.0
    for position in positions:
        fund = resolve_known_etf(position.ticker)
        if fund is not None:
            total += position.weight_pct * fund.us_equity_fraction
    return round(total, 2)


def _stock_over_cap(holding: BookHolding) -> bool:
    return resolve_known_etf(holding.ticker) is None and holding.weight_pct > _NAME_LIMIT


def _theme_over_cap(holding: BookHolding) -> bool:
    fund = resolve_known_etf(holding.ticker)
    return fund is not None and fund.kind == "thematic" and holding.weight_pct > _THEME_LIMIT


def _note_name_concentration(risks: list[str], holding: BookHolding) -> None:
    if holding.weight_pct > _NAME_LIMIT:
        risks.append(f"{holding.ticker} is {holding.weight_pct:.1f}% of the book, above the 20% single-name cap.")


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
