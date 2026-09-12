from __future__ import annotations

from typing import Protocol

from domain.etf.models import EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile


class EtfProvider(Protocol):
    """Normalized ETF metadata and holdings. Implementations must not invent values."""

    name: str

    def get_profile(self, ticker: str) -> EtfProfile | None:
        ...

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        ...

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        ...

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        ...

    def search(self, query: str) -> list[EtfProfile]:
        ...
