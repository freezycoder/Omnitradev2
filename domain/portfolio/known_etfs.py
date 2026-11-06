"""UCITS funds the stock scan does not cover.

Listing aliases collapse to one ticker. The US-equity fraction is an approximate
index mix used only to see when an S&P 500 fund repeats the US sleeve inside
an all-world fund. It is not a live holdings file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EtfKind = Literal["broad_equity", "us_large_cap", "thematic"]


@dataclass(frozen=True)
class KnownEtf:
    ticker: str
    name: str
    kind: EtfKind
    us_equity_fraction: float
    aliases: tuple[str, ...]


_FUNDS = (
    KnownEtf(
        "VWCE",
        "Vanguard FTSE All-World UCITS ETF Acc",
        "broad_equity",
        0.60,
        ("VWCE", "VWRA", "VWRP"),
    ),
    KnownEtf(
        "AUM5",
        "Amundi S&P 500 UCITS ETF EUR Acc",
        "us_large_cap",
        1.0,
        ("AUM5", "500", "0A0P", "A500"),
    ),
    KnownEtf(
        "CSP5",
        "Amundi Core S&P 500 UCITS ETF Acc",
        "us_large_cap",
        1.0,
        ("CSP5", "CSP6"),
    ),
    KnownEtf(
        "QNTM",
        "VanEck Quantum Computing UCITS ETF",
        "thematic",
        0.0,
        ("QNTM", "QUTM", "QNTG"),
    ),
)

_BY_ALIAS = {alias: fund for fund in _FUNDS for alias in fund.aliases}


def resolve_known_etf(ticker: str) -> KnownEtf | None:
    return _BY_ALIAS.get(ticker.upper().strip())


def canonical_ticker(ticker: str) -> str:
    text = ticker.upper().strip()
    fund = _BY_ALIAS.get(text)
    return fund.ticker if fund is not None else text
