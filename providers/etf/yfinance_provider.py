from __future__ import annotations

import contextlib
import importlib
import io
import logging
from threading import RLock
from typing import Any

from domain.etf.models import DATA_UNAVAILABLE, EtfFlowSnapshot, EtfHoldingsSnapshot, EtfProfile, as_fraction, optional_float, optional_int, optional_str
from domain.etf.normalization import normalize_allocation, normalize_holdings, unix_to_date, with_unavailable_fields


_log = logging.getLogger(__name__)
_YFINANCE_LOCK = RLock()


def _yf():
    return importlib.import_module("yfinance")


def _info_map(ticker_obj: Any) -> dict[str, Any]:
    try:
        info = ticker_obj.info or {}
    except Exception:
        _log.warning("yfinance ticker.info failed", exc_info=True)
        return {}
    return info if isinstance(info, dict) else {}


def _funds_data(ticker_obj: Any) -> Any | None:
    try:
        return getattr(ticker_obj, "funds_data", None)
    except Exception:
        return None


class YFinanceEtfProvider:
    name = "yfinance"

    def get_profile(self, ticker: str) -> EtfProfile | None:
        normalized = ticker.upper().strip()
        if not normalized:
            return None
        yf = _yf()
        try:
            with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ticker_obj = yf.Ticker(normalized)
                info = _info_map(ticker_obj)
        except Exception:
            _log.error("yfinance ETF profile failed for %s", normalized, exc_info=True)
            return None
        if not info:
            return None
        expense = (
            as_fraction(info.get("annualReportExpenseRatio"))
            or as_fraction(info.get("netExpenseRatio"))
            or as_fraction(info.get("expenseRatio"))
        )
        dividend = (
            as_fraction(info.get("yield"), percent_if_above=0.2)
            or as_fraction(info.get("dividendYield"), percent_if_above=0.2)
            or as_fraction(info.get("trailingAnnualDividendYield"), percent_if_above=0.2)
        )
        funds = _funds_data(ticker_obj)
        sector_exposure = ()
        if funds is not None:
            sector_exposure = normalize_allocation(getattr(funds, "sector_weightings", None), self.name)
        profile = EtfProfile(
            ticker=normalized,
            name=optional_str(info.get("longName") or info.get("shortName") or info.get("name")),
            issuer=optional_str(info.get("fundFamily") or info.get("family")),
            asset_class=optional_str(info.get("categoryName") or info.get("quoteType")),
            category=optional_str(info.get("category") or info.get("fundCategory") or info.get("categoryName")),
            description=optional_str(info.get("longBusinessSummary") or info.get("description")),
            expense_ratio=expense,
            aum=optional_float(info.get("totalAssets")),
            average_volume=optional_float(info.get("averageVolume") or info.get("averageVolume10days") or info.get("averageDailyVolume10Day")),
            dividend_yield=dividend,
            inception_date=unix_to_date(info.get("fundInceptionDate")),
            holdings_count=optional_int(info.get("holdingsCount")),
            geographic_exposure=(),
            sector_exposure=sector_exposure,
            source=self.name,
            quote_type=optional_str(info.get("quoteType")),
        )
        return with_unavailable_fields(profile)

    def get_holdings(self, ticker: str) -> EtfHoldingsSnapshot | None:
        normalized = ticker.upper().strip()
        if not normalized:
            return None
        yf = _yf()
        try:
            with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                ticker_obj = yf.Ticker(normalized)
                funds = _funds_data(ticker_obj)
                top_holdings = getattr(funds, "top_holdings", None) if funds is not None else None
                sector_weightings = getattr(funds, "sector_weightings", None) if funds is not None else None
        except Exception:
            _log.error("yfinance ETF holdings failed for %s", normalized, exc_info=True)
            return None
        rows = _holdings_from_frame(top_holdings)
        if not rows:
            return None
        return normalize_holdings(
            normalized,
            rows,
            source=self.name,
            sector_allocation=normalize_allocation(sector_weightings, self.name),
        )

    def get_historical_holdings(self, ticker: str) -> list[EtfHoldingsSnapshot]:
        return []

    def get_flows(self, ticker: str) -> EtfFlowSnapshot:
        return EtfFlowSnapshot(
            ticker=ticker.upper().strip(),
            available=False,
            unavailable_reason="yfinance does not publish reliable ETF fund-flow series.",
            source=self.name,
        )

    def search(self, query: str) -> list[EtfProfile]:
        ticker = query.upper().strip()
        if not ticker:
            return []
        profile = self.get_profile(ticker)
        return [profile] if profile is not None else []


def _holdings_from_frame(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    try:
        import pandas as pd
    except Exception:
        return []
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    rows: list[dict[str, Any]] = []
    working = frame.reset_index()
    for record in working.to_dict(orient="records"):
        ticker = (
            record.get("Symbol")
            or record.get("symbol")
            or record.get("Ticker")
            or record.get("index")
            or record.get("Holding")
        )
        name = record.get("Name") or record.get("name") or record.get("Holding Name")
        weight = (
            record.get("Holding Percent")
            or record.get("holdingPercent")
            or record.get("% of net assets")
            or record.get("Weight")
            or record.get("percent")
        )
        rows.append({"ticker": ticker, "name": name, "weight": weight})
    return rows


__all__ = ["YFinanceEtfProvider"]
