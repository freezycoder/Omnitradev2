from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import re
from threading import RLock
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from config.settings import ALLOW_DEMO_FALLBACK, DATA_MODE_AUTO, DATA_MODE_DEMO, DATA_MODE_LIVE, DEMO_DATA_FILE
from providers.news.finnhub_client import build_finnhub_client

if TYPE_CHECKING:
    import yfinance as yf


_log = logging.getLogger(__name__)
_YFINANCE_LOCK = RLock()
_HISTORY_COLUMNS = ("Open", "High", "Low", "Close", "Volume")


def _yf():
    return importlib.import_module("yfinance")


def _load_demo_dataset() -> dict[str, Any]:
    try:
        return json.loads(Path(DEMO_DATA_FILE).read_text())
    except Exception:
        _log.error(
            "Failed to load demo dataset from %s; falling back to empty stocks dict.",
            DEMO_DATA_FILE,
            exc_info=True,
        )
        return {"stocks": {}}


def _build_history_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    history = pd.DataFrame(records)
    if history.empty:
        return history
    date_column = "Date" if "Date" in history.columns else history.columns[0]
    history[date_column] = pd.to_datetime(history[date_column]).dt.tz_localize(None)
    if date_column != "Date":
        history = history.rename(columns={date_column: "Date"})
    history = history.set_index("Date")
    return history[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")


def _normalize_history_frame(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame()
    if isinstance(history.columns, pd.MultiIndex):
        level_values = [list(history.columns.get_level_values(index)) for index in range(history.columns.nlevels)]
        level_index = next(
            (
                index
                for index, values in enumerate(level_values)
                if all(column in set(values) for column in _HISTORY_COLUMNS)
            ),
            0,
        )
        history.columns = history.columns.get_level_values(level_index)

    history = history.loc[:, ~history.columns.duplicated(keep="first")].copy()

    history = history.reset_index()
    date_col = "Datetime" if "Datetime" in history.columns else "Date"
    if date_col not in history.columns:
        date_col = history.columns[0]
    history[date_col] = pd.to_datetime(history[date_col]).dt.tz_localize(None)
    history = history.set_index(date_col)
    if not all(column in history.columns for column in _HISTORY_COLUMNS):
        return pd.DataFrame()
    normalized = history[list(_HISTORY_COLUMNS)].copy()
    for column in _HISTORY_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    return normalized.dropna(how="all")


def load_demo_stock_data(ticker: str) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    dataset = _load_demo_dataset()
    stock = dataset.get("stocks", {}).get(ticker.upper().strip())
    if not stock:
        return None
    history = _build_history_from_records(stock.get("price_history", []))
    fundamentals = stock.get("fundamentals", {})
    if history.empty:
        return None
    return history, fundamentals


def fetch_price_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    yf = _yf()
    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            history = yf.download(
                tickers=ticker,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                timeout=10,
                threads=False,
            )
    except Exception:
        _log.error(
            "yfinance daily download failed for %s (period=%s); returning empty frame so caller can fall back.",
            ticker,
            period,
            exc_info=True,
        )
        return pd.DataFrame()

    return _normalize_history_frame(history)


def fetch_price_histories(tickers: list[str] | tuple[str, ...], period: str = "2y") -> dict[str, pd.DataFrame]:
    normalized = list(dict.fromkeys(str(ticker).upper().strip() for ticker in tickers if str(ticker).strip()))
    if not normalized:
        return {}
    if len(normalized) == 1:
        return {normalized[0]: fetch_price_history(normalized[0], period=period)}

    yf = _yf()
    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            history = yf.download(
                tickers=normalized,
                period=period,
                interval="1d",
                auto_adjust=False,
                progress=False,
                timeout=15,
                threads=True,
                group_by="ticker",
            )
    except Exception:
        _log.error(
            "yfinance batch daily download failed for %s (period=%s); returning empty benchmark frames.",
            ", ".join(normalized),
            period,
            exc_info=True,
        )
        return {ticker: pd.DataFrame() for ticker in normalized}

    if history.empty or not isinstance(history.columns, pd.MultiIndex):
        return {ticker: pd.DataFrame() for ticker in normalized}

    result: dict[str, pd.DataFrame] = {}
    for ticker in normalized:
        symbol_level = next(
            (
                level
                for level in range(history.columns.nlevels)
                if ticker in {str(value).upper() for value in history.columns.get_level_values(level)}
            ),
            None,
        )
        if symbol_level is None:
            result[ticker] = pd.DataFrame()
            continue
        try:
            symbol_history = history.xs(ticker, axis=1, level=symbol_level, drop_level=True)
        except KeyError:
            result[ticker] = pd.DataFrame()
            continue
        result[ticker] = _normalize_history_frame(symbol_history)
    return result


def fetch_intraday_history(ticker: str, interval: str, period: str) -> pd.DataFrame:
    yf = _yf()
    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            history = yf.download(
                tickers=ticker,
                period=period,
                interval=interval,
                auto_adjust=False,
                progress=False,
                timeout=10,
                threads=False,
            )
    except Exception:
        _log.warning(
            "yfinance intraday download failed for %s (interval=%s, period=%s); will retry via Ticker.history.",
            ticker,
            interval,
            period,
            exc_info=True,
        )
        history = pd.DataFrame()

    normalized = _normalize_history_frame(history)
    if not normalized.empty:
        return normalized

    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fallback_history = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    except Exception:
        _log.error(
            "yfinance Ticker.history fallback failed for %s (interval=%s, period=%s); returning empty frame.",
            ticker,
            interval,
            period,
            exc_info=True,
        )
        return pd.DataFrame()
    return _normalize_history_frame(fallback_history)


def fetch_live_intraday_data(ticker: str) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    intraday_15m = fetch_intraday_history(ticker, interval="15m", period="5d")
    intraday_60m = fetch_intraday_history(ticker, interval="60m", period="1mo")

    if not intraday_15m.empty and not intraday_60m.empty:
        return intraday_15m, intraday_60m, None
    if not intraday_15m.empty or not intraday_60m.empty:
        return intraday_15m, intraday_60m, "Live intraday data was only partially available."
    return pd.DataFrame(), pd.DataFrame(), "Live intraday data was unavailable."


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    yf = _yf()
    info: dict[str, Any] = {}
    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            info = yf.Ticker(ticker).info or {}
    except Exception:
        _log.error(
            "yfinance fundamentals fetch failed for %s; returning empty fundamentals dict.",
            ticker,
            exc_info=True,
        )
        return {}

    fifty_two_week_low = info.get("fiftyTwoWeekLow")
    fifty_two_week_high = info.get("fiftyTwoWeekHigh")
    week_range = None
    if fifty_two_week_low is not None and fifty_two_week_high is not None:
        week_range = f"${fifty_two_week_low:,.2f} - ${fifty_two_week_high:,.2f}"

    return {
        "shortName": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "dividendYield": info.get("dividendYield"),
        "revenueGrowth": info.get("revenueGrowth"),
        "earningsGrowth": info.get("earningsGrowth"),
        "profitMargins": info.get("profitMargins"),
        "operatingMargins": info.get("operatingMargins"),
        "returnOnEquity": info.get("returnOnEquity"),
        "currentRatio": info.get("currentRatio"),
        "debtToEquity": info.get("debtToEquity"),
        "beta": info.get("beta"),
        "averageVolume": info.get("averageVolume"),
        "fiftyTwoWeekRange": week_range,
    }


def _first_date_iso(value: Any) -> str | None:
    candidates = value if isinstance(value, (list, tuple)) else [value]
    for candidate in candidates:
        if candidate is None or candidate == "":
            continue
        try:
            parsed = pd.Timestamp(candidate)
        except (TypeError, ValueError):
            continue
        if not pd.isna(parsed):
            return parsed.date().isoformat()
    return None


def _dataframe_row(frame: Any, label: str) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty or label not in frame.index:
        return {}
    row = frame.loc[label]
    if isinstance(row, pd.DataFrame):
        row = row.iloc[0]
    if not isinstance(row, pd.Series):
        return {}
    return {
        str(key): value
        for key, value in row.to_dict().items()
        if not pd.isna(value)
    }


def fetch_earnings_estimate_context(ticker: str) -> dict[str, Any]:
    yf = _yf()
    calendar: dict[str, Any] = {}
    earnings_estimate = pd.DataFrame()
    eps_revisions = pd.DataFrame()
    unavailable: list[str] = []
    with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            ticker_obj = yf.Ticker(ticker)
        except Exception:
            _log.info("yfinance earnings ticker was unavailable for %s.", ticker, exc_info=True)
            return {
                "status": "unavailable",
                "next_earnings_date": None,
                "current_quarter": {},
                "revisions": {},
                "message": "Yahoo Finance earnings intelligence was unavailable.",
            }
        try:
            raw_calendar = ticker_obj.calendar
            calendar = raw_calendar if isinstance(raw_calendar, dict) else {}
        except Exception:
            unavailable.append("earnings calendar")
            _log.info("yfinance earnings calendar was unavailable for %s.", ticker, exc_info=True)
        try:
            raw_estimates = ticker_obj.earnings_estimate
            earnings_estimate = (
                raw_estimates
                if isinstance(raw_estimates, pd.DataFrame)
                else pd.DataFrame()
            )
        except Exception:
            unavailable.append("quarterly consensus")
            _log.info("yfinance earnings estimates were unavailable for %s.", ticker, exc_info=True)
        try:
            raw_revisions = ticker_obj.eps_revisions
            eps_revisions = (
                raw_revisions
                if isinstance(raw_revisions, pd.DataFrame)
                else pd.DataFrame()
            )
        except Exception:
            unavailable.append("estimate revisions")
            _log.info("yfinance EPS revisions were unavailable for %s.", ticker, exc_info=True)

    estimate_row = _dataframe_row(earnings_estimate, "0q")
    revision_row = _dataframe_row(eps_revisions, "0q")
    growth = estimate_row.get("growth")
    try:
        growth_pct = float(growth) * 100 if growth is not None and pd.notna(growth) else None
    except (TypeError, ValueError):
        growth_pct = None
    current_quarter = {
        "average": estimate_row.get("avg"),
        "low": estimate_row.get("low"),
        "high": estimate_row.get("high"),
        "year_ago_eps": estimate_row.get("yearAgoEps"),
        "analyst_count": estimate_row.get("numberOfAnalysts"),
        "growth_pct": growth_pct,
    }
    revisions = {
        "up_7d": revision_row.get("upLast7days"),
        "up_30d": revision_row.get("upLast30days"),
        "down_7d": revision_row.get("downLast7Days"),
        "down_30d": revision_row.get("downLast30days"),
    }
    has_calendar = _first_date_iso(calendar.get("Earnings Date")) is not None
    has_estimate = bool(estimate_row)
    has_revisions = bool(revision_row)
    if has_calendar and has_estimate and has_revisions:
        status = "available"
    elif has_calendar or has_estimate or has_revisions:
        status = "partial"
    else:
        status = "unavailable"
    message = (
        f"Yahoo Finance did not provide {', '.join(unavailable)}."
        if unavailable
        else None
    )
    return {
        "status": status,
        "next_earnings_date": _first_date_iso(calendar.get("Earnings Date")),
        "current_quarter": current_quarter,
        "revisions": revisions,
        "message": message,
    }


def _normalize_statement_label(label: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(label).lower())


def _statement_frame(ticker_obj: Any, attribute_names: tuple[str, ...]) -> pd.DataFrame:
    for attribute_name in attribute_names:
        try:
            frame = getattr(ticker_obj, attribute_name)
        except Exception:
            _log.debug(
                "yfinance attribute %s unavailable on ticker_obj; trying next alias.",
                attribute_name,
                exc_info=True,
            )
            continue
        if isinstance(frame, pd.DataFrame) and not frame.empty:
            return frame
    return pd.DataFrame()


def _prepare_statement_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    cleaned = frame.copy()
    cleaned = cleaned.loc[~cleaned.index.duplicated(keep="first")]
    dated_columns = []
    for column in cleaned.columns:
        try:
            dated_columns.append((column, pd.to_datetime(column)))
        except Exception:
            _log.debug("Could not parse statement column %r as date; treating as undated.", column, exc_info=True)
            dated_columns.append((column, pd.NaT))
    ordered = [column for column, _ in sorted(dated_columns, key=lambda item: item[1] if pd.notna(item[1]) else pd.Timestamp.min)]
    cleaned = cleaned[ordered[-4:]]
    return cleaned


def _extract_statement_series(frame: pd.DataFrame, aliases: tuple[str, ...]) -> list[float]:
    if frame.empty:
        return []
    normalized_index = {_normalize_statement_label(index): index for index in frame.index}
    for alias in aliases:
        index = normalized_index.get(_normalize_statement_label(alias))
        if index is None:
            continue
        series: list[float] = []
        for value in frame.loc[index].tolist():
            if isinstance(value, (int, float)) and pd.notna(value):
                series.append(float(value))
        return series
    return []


def _sum_statement_series(frame: pd.DataFrame, aliases: tuple[str, ...]) -> list[float]:
    if frame.empty:
        return []
    normalized_index = {_normalize_statement_label(index): index for index in frame.index}
    rows = [normalized_index[_normalize_statement_label(alias)] for alias in aliases if _normalize_statement_label(alias) in normalized_index]
    if not rows:
        return []
    subset = frame.loc[rows]
    if isinstance(subset, pd.Series):
        subset = subset.to_frame().T
    totals = subset.fillna(0).sum(axis=0).tolist()
    return [float(value) for value in totals if isinstance(value, (int, float)) and pd.notna(value)]


def fetch_financial_statement_metrics(ticker: str) -> dict[str, Any]:
    yf = _yf()
    try:
        with _YFINANCE_LOCK, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            ticker_obj = yf.Ticker(ticker)
            income_frame = _prepare_statement_frame(
                _statement_frame(ticker_obj, ("income_stmt", "financials", "income_stmt_freq"))
            )
            cashflow_frame = _prepare_statement_frame(
                _statement_frame(ticker_obj, ("cash_flow", "cashflow"))
            )
            balance_frame = _prepare_statement_frame(
                _statement_frame(ticker_obj, ("balance_sheet", "balancesheet"))
            )
    except Exception:
        _log.error(
            "yfinance financial statement fetch failed for %s; returning empty metrics.",
            ticker,
            exc_info=True,
        )
        return {}

    reference_frame = next((frame for frame in (income_frame, cashflow_frame, balance_frame) if not frame.empty), pd.DataFrame())
    periods = [pd.to_datetime(column).strftime("%Y-%m-%d") for column in reference_frame.columns] if not reference_frame.empty else []

    revenue = _extract_statement_series(income_frame, ("Total Revenue", "Operating Revenue", "Revenue"))
    net_income = _extract_statement_series(income_frame, ("Net Income", "Net Income Common Stockholders", "Net Income Including Noncontrolling Interests"))
    operating_cash_flow = _extract_statement_series(cashflow_frame, ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Net Cash Provided By Operating Activities"))
    free_cash_flow = _extract_statement_series(cashflow_frame, ("Free Cash Flow",))
    capex = _extract_statement_series(cashflow_frame, ("Capital Expenditure", "Capital Expenditures"))
    if not free_cash_flow and operating_cash_flow and capex and len(operating_cash_flow) == len(capex):
        free_cash_flow = [ocf + cap for ocf, cap in zip(operating_cash_flow, capex)]

    metrics = {
        "periods": periods,
        "revenue": revenue,
        "net_income": net_income,
        "operating_cash_flow": operating_cash_flow,
        "free_cash_flow": free_cash_flow,
        "receivables": _extract_statement_series(balance_frame, ("Accounts Receivable", "Net Receivables", "Receivables")),
        "total_assets": _extract_statement_series(balance_frame, ("Total Assets",)),
        "current_assets": _extract_statement_series(balance_frame, ("Current Assets", "Total Current Assets")),
        "current_liabilities": _extract_statement_series(balance_frame, ("Current Liabilities", "Total Current Liabilities")),
        "common_shares": _extract_statement_series(
            balance_frame,
            ("Ordinary Shares Number", "Share Issued", "Common Stock Shares Outstanding"),
        ),
        "gross_profit": _extract_statement_series(income_frame, ("Gross Profit",)),
        "operating_expense": _extract_statement_series(income_frame, ("Operating Expense", "Operating Expenses", "Total Operating Expenses")),
        "goodwill": _extract_statement_series(balance_frame, ("Goodwill",)),
        "intangibles": _extract_statement_series(balance_frame, ("Other Intangible Assets", "Intangible Assets", "Goodwill And Other Intangible Assets")),
        "total_debt": _extract_statement_series(balance_frame, ("Total Debt", "Net Debt", "Total Borrowings")),
        "special_items": _sum_statement_series(
            income_frame,
            ("Special Income Charges", "Special Charges", "Restructuring And Mergern Acquisition", "Other Non Operating Income Expenses"),
        ),
    }

    if not metrics["total_debt"]:
        current_debt = _extract_statement_series(balance_frame, ("Current Debt", "Current Debt And Capital Lease Obligation"))
        long_term_debt = _extract_statement_series(balance_frame, ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"))
        if current_debt and long_term_debt and len(current_debt) == len(long_term_debt):
            metrics["total_debt"] = [current + long for current, long in zip(current_debt, long_term_debt)]

    return metrics


def fetch_live_market_data(ticker: str) -> tuple[pd.DataFrame, dict[str, Any], str | None]:
    history = fetch_price_history(ticker)
    if history.empty:
        return pd.DataFrame(), {}, "Live price history was unavailable."

    fundamentals = fetch_fundamentals(ticker)
    if fundamentals:
        return history, fundamentals, None
    return history, {}, "Live fundamentals were unavailable."


def load_market_data(ticker: str, mode: str = DATA_MODE_AUTO) -> tuple[pd.DataFrame, dict[str, Any], str, str | None]:
    normalized_ticker = ticker.upper().strip()

    if mode == DATA_MODE_DEMO:
        demo_data = load_demo_stock_data(normalized_ticker)
        if demo_data is None:
            return pd.DataFrame(), {}, "demo", "Demo data is not available for this ticker."
        history, fundamentals = demo_data
        return history, fundamentals, "demo", "Using demo data for testing."

    live_history, live_fundamentals, live_message = fetch_live_market_data(normalized_ticker)
    if not live_history.empty:
        return live_history, live_fundamentals, "live", live_message

    if mode == DATA_MODE_LIVE:
        return pd.DataFrame(), {}, "live", live_message or "Live market data is unavailable for this ticker."

    if ALLOW_DEMO_FALLBACK:
        demo_data = load_demo_stock_data(normalized_ticker)
        if demo_data is not None:
            history, fundamentals = demo_data
            return history, fundamentals, "demo", "Using demo data because live data is unavailable."

    return pd.DataFrame(), {}, "live", live_message or "Market data is unavailable for this ticker."


def merge_profile_into_fundamentals(fundamentals: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fundamentals)
    if not profile:
        return merged
    merged.setdefault("shortName", profile.get("name"))
    merged.setdefault("sector", profile.get("finnhubIndustry"))
    if not merged.get("marketCap") and profile.get("marketCapitalization"):
        merged["marketCap"] = float(profile["marketCapitalization"]) * 1_000_000
    return merged


def apply_quote_to_latest_history(history: pd.DataFrame, quote: dict[str, Any] | None = None) -> pd.DataFrame:
    if history.empty or not quote:
        return history
    quote_price = quote.get("c")
    if not isinstance(quote_price, (int, float)) or quote_price <= 0:
        return history

    adjusted = history.copy()
    latest_index = adjusted.index[-1]
    latest = adjusted.loc[latest_index]
    latest_close = latest.get("Close")
    close_is_valid = isinstance(latest_close, (int, float)) and latest_close > 0
    open_high_low_are_placeholders = any(
        not isinstance(latest.get(column), (int, float)) or latest.get(column) <= 0
        for column in ("Open", "High", "Low")
    )
    close_gap = abs((float(latest_close) - float(quote_price)) / float(quote_price)) if close_is_valid else 1.0

    if not open_high_low_are_placeholders and close_gap <= 0.20:
        return history

    adjusted.loc[latest_index, "Close"] = float(quote_price)
    adjusted.loc[latest_index, "Open"] = float(quote_price) if latest.get("Open", 0) <= 0 else latest["Open"]
    adjusted.loc[latest_index, "High"] = max(float(adjusted.loc[latest_index, "Open"]), float(quote_price), float(latest.get("High") or 0))
    positive_low_candidates = [
        float(value)
        for value in (adjusted.loc[latest_index, "Open"], quote_price, latest.get("Low"))
        if isinstance(value, (int, float)) and value > 0
    ]
    adjusted.loc[latest_index, "Low"] = min(positive_low_candidates) if positive_low_candidates else float(quote_price)
    return adjusted


def fetch_finnhub_bundle(ticker: str) -> tuple[dict[str, Any], str | None]:
    client = build_finnhub_client()
    if not client.enabled:
        return {
            "quote": {},
            "profile": {},
            "news": [],
            "earnings_history": [],
        }, "Finnhub API key is not configured."

    quote_response = client.get_quote(ticker)
    if quote_response.error in {"Finnhub is unavailable right now.", "Finnhub rate limit reached."}:
        return {
            "quote": {},
            "profile": {},
            "news": [],
            "earnings_history": [],
        }, quote_response.error

    profile_response = client.get_company_profile(ticker)
    news_response = client.get_company_news(ticker)
    earnings_response = client.get_company_earnings(ticker)

    messages = [
        message
        for message in [
            quote_response.error,
            profile_response.error,
            news_response.error,
            earnings_response.error,
        ]
        if message
    ]
    bundle = {
        "quote": quote_response.payload or {},
        "profile": profile_response.payload or {},
        "news": news_response.payload or [],
        "earnings_history": earnings_response.payload or [],
    }
    return bundle, "; ".join(dict.fromkeys(messages)) if messages else None


def build_snapshot(history: pd.DataFrame, quote: dict[str, Any] | None = None) -> dict[str, float | None] | None:
    if history.empty:
        return None

    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) >= 2 else latest
    current_price = float(latest["Close"])
    daily_change_abs = float(latest["Close"] - previous["Close"])
    daily_change_pct = (daily_change_abs / float(previous["Close"])) * 100 if previous["Close"] else 0.0
    if quote:
        quote_price = quote.get("c")
        quote_change_abs = quote.get("d")
        quote_change_pct = quote.get("dp")
        if isinstance(quote_price, (int, float)) and quote_price > 0:
            current_price = float(quote_price)
        if isinstance(quote_change_abs, (int, float)):
            daily_change_abs = float(quote_change_abs)
        if isinstance(quote_change_pct, (int, float)):
            daily_change_pct = float(quote_change_pct)

    return {
        "current_price": current_price,
        "daily_change_abs": daily_change_abs,
        "daily_change_pct": daily_change_pct,
        "volume": float(latest["Volume"]),
        "avg_volume_20": float(history["Volume"].tail(20).mean()),
        "rsi": float(latest["RSI"]) if pd.notna(latest.get("RSI")) else None,
    }
