from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from api.response_cache import TtlResponseCache
from api.security import (
    REFRESH_RATE_LIMIT,
    SecurityHeadersMiddleware,
    enforce_rate_limit,
    enforce_write_token,
    is_production,
    public_error_message,
)
from config.access import api_capabilities_snapshot


log = logging.getLogger(__name__)

DATA_MODE_AUTO = "auto"
DATA_MODE_LIVE = "live"
DATA_MODE_DEMO = "demo"
DATA_MODES = {DATA_MODE_AUTO, DATA_MODE_LIVE, DATA_MODE_DEMO}
SERVICE_TIMEOUT_SECONDS = 90.0
PRICE_MODES = {"cached", "live"}
HOSTED_DATA_SEED_VERSION = os.environ.get("OMNITRADE_DATA_SEED_VERSION", "2026-06-23.3")
MIN_CACHED_UNIVERSE_COVERAGE = 0.80
ANALYTICS_CACHE_TTL_SECONDS = 120.0
_OVERVIEW_REFRESH_LOCK = Lock()
_OVERVIEW_REFRESH_STATE_LOCK = Lock()
_OVERVIEW_REFRESH_JOB: dict[str, Any] | None = None
_ANALYTICS_RESPONSE_CACHE = TtlResponseCache()


class WatchlistMutation(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-]+$")
    source: str = Field(default="frontend", min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")


class PerformanceLogMutation(BaseModel):
    ticker: str = Field(min_length=1, max_length=12, pattern=r"^[A-Za-z0-9.\-]+$")
    strategy_family: Literal["short_term_day", "short_term_swing"]
    opened_on: date
    closed_on: date
    score: float = Field(ge=0, le=100)
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    status: Literal["hit_target", "hit_stop", "expired"]


DEFAULT_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
]

PRIVATE_NETWORK_ORIGIN_REGEX = (
    r"https?://("
    r"localhost|127\.0\.0\.1|"
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|"
    r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
    r")(:\d+)?"
)


def _env_csv(name: str) -> list[str]:
    return [value.strip() for value in os.environ.get(name, "").split(",") if value.strip()]


def _cors_origin_regex(
    *,
    environment: str | None = None,
    configured_regex: str | None = None,
) -> str | None:
    if configured_regex is None:
        configured_regex = os.environ.get("OMNITRADE_CORS_ORIGIN_REGEX")
    if configured_regex is not None:
        return configured_regex.strip() or None
    active_environment = (environment or os.environ.get("ENV", "production")).strip().lower()
    return None if active_environment == "production" else PRIVATE_NETWORK_ORIGIN_REGEX


_HIDE_DOCS = is_production()

app = FastAPI(
    title="OmniTrade API",
    version="1.0.0",
    description="JSON API adapter over the existing OmniTrade application services.",
    docs_url=None if _HIDE_DOCS else "/docs",
    redoc_url=None if _HIDE_DOCS else "/redoc",
    openapi_url=None if _HIDE_DOCS else "/openapi.json",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*DEFAULT_CORS_ORIGINS, *_env_csv("OMNITRADE_CORS_ORIGINS")],
    allow_origin_regex=_cors_origin_regex(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-OmniTrade-Write-Token"],
)


def _bootstrap_database() -> None:
    from storage.sqlite import bootstrap_database

    bootstrap_database()


def _require_user_mutation(operation: str, request: Request | None = None) -> None:
    capabilities = api_capabilities_snapshot()
    if not capabilities["user_mutations_enabled"]:
        log.warning("Blocked %s because the API is running in read-only mode", operation)
        raise HTTPException(
            status_code=403,
            detail={
                "error": "read_only_deployment",
                "operation": operation,
                "message": capabilities["message"],
            },
        )
    if request is not None:
        enforce_write_token(request)
        enforce_rate_limit(request, bucket="mutation")


def _dataframe_to_records(frame: Any) -> list[dict[str, Any]]:
    import pandas as pd

    if frame.empty:
        return []

    payload = frame.reset_index().copy()
    for column in payload.columns:
        if pd.api.types.is_datetime64_any_dtype(payload[column]):
            payload[column] = pd.to_datetime(payload[column]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return payload.to_dict(orient="records")


def _to_jsonable(value: Any) -> Any:
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - lets `import api.main` work before app deps are installed.
        pd = None

    try:
        import numpy as np
    except Exception:  # pragma: no cover - lets `import api.main` work before app deps are installed.
        np = None

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value):
        return _to_jsonable(asdict(value))

    if pd is not None and isinstance(value, pd.DataFrame):
        return _to_jsonable(_dataframe_to_records(value))

    if pd is not None and isinstance(value, pd.Series):
        return _to_jsonable(value.to_list())

    if pd is not None and isinstance(value, pd.Timestamp):
        return value.isoformat()

    if np is not None:
        if isinstance(value, np.ndarray):
            return _to_jsonable(value.tolist())
        if isinstance(value, np.generic):
            return _to_jsonable(value.item())

    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _to_jsonable(value.to_dict())

    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))

    return value


def _json_response(payload: Any) -> Any:
    return jsonable_encoder(_to_jsonable(payload))


async def _run_service(
    name: str,
    fn: Callable[[], Any],
    *,
    timeout_seconds: float = SERVICE_TIMEOUT_SECONDS,
) -> Any:
    try:
        payload = await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_seconds)
    except TimeoutError as exc:
        log.warning("%s timed out after %.1fs", name, timeout_seconds)
        raise HTTPException(
            status_code=504,
            detail={
                "error": "service_timeout",
                "service": name,
                "message": f"{name} did not finish within {timeout_seconds:.0f} seconds.",
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("%s failed", name)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "service_error",
                "service": name,
                "message": public_error_message(exc),
            },
        ) from exc

    return _json_response(payload)


def _validate_data_mode(data_mode: str) -> str:
    normalized = data_mode.strip().lower()
    if normalized not in DATA_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_data_mode",
                "message": f"data_mode must be one of {sorted(DATA_MODES)}.",
            },
        )
    return normalized


def _validate_price_mode(price_mode: str) -> str:
    normalized = price_mode.strip().lower()
    if normalized not in PRICE_MODES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_price_mode",
                "message": f"price_mode must be one of {sorted(PRICE_MODES)}.",
            },
        )
    return normalized


def _cached_scan_covers_universe(cached: dict[str, Any], tickers: list[str]) -> bool:
    expected = {ticker.upper().strip() for ticker in tickers}
    cached_universe = {str(ticker).upper().strip() for ticker in cached.get("universe", []) if str(ticker).strip()}
    if not cached_universe:
        cached_universe = {
            str(row.get("ticker")).upper().strip()
            for section in ("market_rows", "long_term", "short_term")
            for row in cached.get(section, [])
            if isinstance(row, dict) and row.get("ticker")
        }
    if not expected:
        return bool(cached_universe)
    coverage = len(expected & cached_universe) / len(expected)
    return coverage >= MIN_CACHED_UNIVERSE_COVERAGE


def _cached_scan_missing_tickers(cached: dict[str, Any], tickers: list[str]) -> list[str]:
    expected = {ticker.upper().strip() for ticker in tickers}
    cached_universe = {str(ticker).upper().strip() for ticker in cached.get("universe", []) if str(ticker).strip()}
    return sorted(expected - cached_universe)


def _overview_universe_config(universe_key: str) -> dict[str, Any]:
    from config.universe import UNIVERSE_REGISTRY

    if universe_key not in UNIVERSE_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_universe",
                "message": f"universe must be one of {sorted(UNIVERSE_REGISTRY)}.",
            },
        )
    return UNIVERSE_REGISTRY[universe_key]


def _load_cached_overview_payload(
    *,
    universe_key: str,
    universe_config: dict[str, Any],
    api_note: str,
) -> dict[str, Any] | None:
    from domain.signals.freshness import apply_scan_freshness_policy
    from storage.repositories.scan_repository import load_latest_view_scan, load_named_scan_cache

    cached = load_named_scan_cache(universe_key)
    latest = load_latest_view_scan()
    if not cached and latest and latest.get("universe_name") == universe_config["name"]:
        cached = latest
    if cached and _cached_scan_covers_universe(cached, universe_config["tickers"]):
        missing_tickers = _cached_scan_missing_tickers(cached, universe_config["tickers"])
        coverage_note = ""
        if missing_tickers:
            coverage_note = (
                f" Cached scan covers {len(universe_config['tickers']) - len(missing_tickers)} of "
                f"{len(universe_config['tickers'])} configured tickers; refresh to include "
                f"{', '.join(missing_tickers)}."
            )
        protected = apply_scan_freshness_policy(cached, source_override="cached_real")
        return {
            **protected,
            "api_note": f"{api_note}{coverage_note}",
        }
    return None


def _load_demo_overview_payload(
    *,
    universe_key: str,
    universe_config: dict[str, Any],
    api_note: str,
) -> dict[str, Any]:
    from application.scan_service import run_scan

    payload = run_scan(
        universe=universe_config["tickers"],
        data_mode=DATA_MODE_DEMO,
        universe_name=universe_config["name"],
        cache_key=universe_key,
    )
    return {
        **payload,
        "api_note": api_note,
    }


def _load_overview_fallback_payload(*, universe_key: str, reason: str) -> dict[str, Any]:
    universe_config = _overview_universe_config(universe_key)
    cached = _load_cached_overview_payload(
        universe_key=universe_key,
        universe_config=universe_config,
        api_note=f"{reason} Returned the latest cached scan instead.",
    )
    if cached:
        return cached

    return _load_demo_overview_payload(
        universe_key=universe_key,
        universe_config=universe_config,
        api_note=f"{reason} No cached scan was available, so the API returned a fast demo seed.",
    )


def _overview_scan_payload(*, data_mode: str, universe_key: str) -> dict[str, Any]:
    from application.scan_service import run_scan

    universe_config = _overview_universe_config(universe_key)
    return run_scan(
        universe=universe_config["tickers"],
        data_mode=data_mode,
        universe_name=universe_config["name"],
        cache_key=universe_key,
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _refresh_job_public_snapshot(job: dict[str, Any] | None = None) -> dict[str, Any]:
    with _OVERVIEW_REFRESH_STATE_LOCK:
        current = dict(job if job is not None else (_OVERVIEW_REFRESH_JOB or {}))

    if not current:
        return {
            "refresh_status": "idle",
            "status": "idle",
            "message": "No overview refresh has been requested in this API process.",
        }
    return {
        "refresh_status": current.get("status", "idle"),
        "status": current.get("status", "idle"),
        "job_id": current.get("job_id"),
        "universe": current.get("universe"),
        "data_mode": current.get("data_mode"),
        "started_at": current.get("started_at"),
        "finished_at": current.get("finished_at"),
        "updated_at": current.get("updated_at"),
        "source": current.get("source"),
        "message": current.get("message"),
        "error": current.get("error"),
    }


def _store_refresh_job_update(job_id: str, **updates: Any) -> None:
    with _OVERVIEW_REFRESH_STATE_LOCK:
        if not _OVERVIEW_REFRESH_JOB or _OVERVIEW_REFRESH_JOB.get("job_id") != job_id:
            return
        _OVERVIEW_REFRESH_JOB.update(updates)


def _run_overview_refresh_job(job_id: str, *, data_mode: str, universe_key: str) -> None:
    try:
        payload = _overview_scan_payload(data_mode=data_mode, universe_key=universe_key)
        _store_refresh_job_update(
            job_id,
            status="complete",
            finished_at=_now_iso(),
            updated_at=payload.get("updated_at"),
            source=payload.get("source"),
            message="Refresh complete. The newest scan snapshot has been published.",
            error=None,
        )
    except Exception as exc:
        log.exception("overview refresh job failed")
        _store_refresh_job_update(
            job_id,
            status="failed",
            finished_at=_now_iso(),
            message="Refresh failed before a newer scan snapshot could be published.",
            error=str(exc),
        )
    finally:
        _OVERVIEW_REFRESH_LOCK.release()


def _start_overview_refresh_job(*, data_mode: str, universe_key: str) -> dict[str, Any]:
    if not _OVERVIEW_REFRESH_LOCK.acquire(blocking=False):
        return {**_refresh_job_public_snapshot(), "already_running": True}

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "running",
        "universe": universe_key,
        "data_mode": data_mode,
        "started_at": _now_iso(),
        "finished_at": None,
        "updated_at": None,
        "source": None,
        "message": "A live overview refresh is running in the background.",
        "error": None,
    }
    with _OVERVIEW_REFRESH_STATE_LOCK:
        global _OVERVIEW_REFRESH_JOB
        _OVERVIEW_REFRESH_JOB = job
    initial_snapshot = _refresh_job_public_snapshot(job)

    try:
        Thread(
            target=_run_overview_refresh_job,
            kwargs={"job_id": job_id, "data_mode": data_mode, "universe_key": universe_key},
            daemon=True,
        ).start()
    except Exception:
        _store_refresh_job_update(
            job_id,
            status="failed",
            finished_at=_now_iso(),
            message="Refresh could not be started.",
        )
        _OVERVIEW_REFRESH_LOCK.release()
        raise

    return {**initial_snapshot, "already_running": False}


def _load_overview_refresh_status(*, universe_key: str) -> dict[str, Any]:
    status = _refresh_job_public_snapshot()
    if status.get("universe") not in (None, universe_key):
        return {
            **status,
            "message": f"A refresh is running for {status.get('universe')}; {universe_key} is waiting for that job to finish.",
        }
    return status


def _load_overview_payload(*, refresh: bool, data_mode: str, universe_key: str) -> dict[str, Any]:
    universe_config = _overview_universe_config(universe_key)
    if refresh:
        job = _start_overview_refresh_job(data_mode=data_mode, universe_key=universe_key)
        payload = _load_overview_fallback_payload(
            universe_key=universe_key,
            reason="A live overview refresh is running in the background.",
        )
        return {
            **payload,
            "refresh_status": job["refresh_status"],
            "refresh_job": job,
            "api_note": (
                (
                    "A live overview refresh is already running. "
                    if job.get("already_running")
                    else "A live overview refresh is running in the background. "
                )
                + "The previous snapshot stays visible until the refreshed cache is published."
            ),
        }

    cached = _load_cached_overview_payload(
        universe_key=universe_key,
        universe_config=universe_config,
        api_note="Returned latest cached scan. Pass refresh=true to run a new scan.",
    )
    if cached:
        return cached

    # Render's free instances often boot with an empty local filesystem. Avoid
    # making the first default page load run the full live scanner, which can
    # exceed the API timeout before any cache exists. Manual refresh and
    # explicit live mode still run the live path.
    if not refresh and data_mode == DATA_MODE_AUTO:
        return _load_demo_overview_payload(
            universe_key=universe_key,
            universe_config=universe_config,
            api_note=(
                "No cached scan was available, so the API returned a fast demo seed. "
                "Use Refresh Scan to run a fresh live scan."
            ),
        )

    return _overview_scan_payload(data_mode=data_mode, universe_key=universe_key)


def _entry_trigger_lab_service(price_mode: str) -> Any:
    from application.entry_trigger_lab_service import EntryTriggerLabService
    from application.outcome_evaluation_service import OutcomeEvaluationService, _history_from_records
    from storage.repositories.outcome_repository import OutcomeRepository
    from storage.repositories.signal_repository import SignalRepository
    from storage.repositories.ticker_repository import load_cached_ticker_data

    if price_mode == "live":
        return EntryTriggerLabService()

    class CachedOnlyOutcomeEvaluationService(OutcomeEvaluationService):
        def _load_day_trade_history(self, signal: Any) -> Any:
            cached = load_cached_ticker_data(signal.ticker) or {}
            history = _history_from_records(cached.get("intraday_15m", []) or cached.get("history", []))
            if history.empty:
                return history
            history = history.sort_index()
            history.index = history.index.tz_localize(None)
            return history

        def _load_swing_history(self, signal: Any) -> Any:
            cached = load_cached_ticker_data(signal.ticker) or {}
            history = _history_from_records(cached.get("history", []))
            if history.empty:
                return history
            history = history.sort_index()
            history.index = history.index.tz_localize(None)
            return history

    class CachedEntryTriggerLabService(EntryTriggerLabService):
        def __init__(self) -> None:
            signal_repository = SignalRepository()
            outcome_repository = OutcomeRepository()
            super().__init__(
                signal_repository=signal_repository,
                outcome_repository=outcome_repository,
                outcome_evaluation_service=CachedOnlyOutcomeEvaluationService(
                    signal_repository=signal_repository,
                    outcome_repository=outcome_repository,
                ),
            )
            self._api_payload_cache: dict[tuple[Any, ...], dict[str, Any]] = {}

        def build_entry_trigger_payload(self, strategy_family: str | None, **kwargs: Any) -> dict[str, Any]:
            key = (
                strategy_family,
                kwargs.get("min_resolved"),
                kwargs.get("min_score"),
                kwargs.get("trend_direction"),
                kwargs.get("trade_state"),
            )
            if key not in self._api_payload_cache:
                self._api_payload_cache[key] = super().build_entry_trigger_payload(strategy_family, **kwargs)
            return self._api_payload_cache[key]

    return CachedEntryTriggerLabService()


def _strategy_execution_service(price_mode: str, *, entry_trigger_lab_service: Any | None = None) -> Any:
    from application.strategy_execution_service import ExecutionPriceSnapshot, StrategyExecutionService

    if price_mode == "live":
        return StrategyExecutionService(entry_trigger_lab_service=entry_trigger_lab_service)

    class CachedOnlyStrategyExecutionService(StrategyExecutionService):
        def _fetch_live_price(self, signal: Any) -> ExecutionPriceSnapshot:
            return ExecutionPriceSnapshot(current_price=None, price_source="api_cached_only", volatility_proxy_pct=None)

    return CachedOnlyStrategyExecutionService(
        entry_trigger_lab_service=entry_trigger_lab_service or _entry_trigger_lab_service(price_mode)
    )


def _performance_lab_service(price_mode: str) -> Any:
    from application.performance_lab_service import PerformanceLabService

    entry_trigger_lab_service = _entry_trigger_lab_service(price_mode)
    return PerformanceLabService(
        entry_trigger_lab_service=entry_trigger_lab_service,
        strategy_execution_service=_strategy_execution_service(
            price_mode,
            entry_trigger_lab_service=entry_trigger_lab_service,
        ),
    )


def _dashboard_payload(*, price_mode: str) -> dict[str, Any]:
    return _performance_lab_service(price_mode).build_dashboard_payload()


def _performance_payload(*, price_mode: str) -> dict[str, Any]:
    from config.performance import SUPPORTED_SIGNAL_STRATEGIES

    service = _performance_lab_service(price_mode)
    overall = service.get_dashboard_summary()

    return {
        "overall": overall,
        "performance_assumptions": service.get_performance_assumptions(),
        "risk_context": service.get_performance_risk_context(overall),
        "by_strategy": {
            strategy: service.get_strategy_summary(strategy)
            for strategy in SUPPORTED_SIGNAL_STRATEGIES
        },
        "score_buckets": service.get_score_buckets(),
        "entry_trigger_lab": service.get_entry_trigger_lab_payload(),
        "trigger_sensitivity": service.get_trigger_sensitivity_payload(),
        "recent_outcomes": service.get_recent_outcomes(limit=25),
    }


def _cached_analytics_payload(
    service: str,
    *,
    price_mode: str,
    factory: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    return _ANALYTICS_RESPONSE_CACHE.get_or_create(
        (service, price_mode),
        ttl_seconds=ANALYTICS_CACHE_TTL_SECONDS,
        factory=factory,
    )


def _log_performance_entry(payload: PerformanceLogMutation) -> dict[str, Any]:
    from application.manual_performance_log_service import (
        DuplicatePerformanceEntryError,
        ManualPerformanceLogService,
    )

    try:
        entry = ManualPerformanceLogService().log_completed_trade(
            ticker=payload.ticker,
            strategy_family=payload.strategy_family,
            opened_on=payload.opened_on,
            closed_on=payload.closed_on,
            score=payload.score,
            entry_price=payload.entry_price,
            exit_price=payload.exit_price,
            status=payload.status,
        )
    except DuplicatePerformanceEntryError as exc:
        raise HTTPException(status_code=409, detail={"error": "duplicate_performance_entry", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": "invalid_performance_entry", "message": str(exc)}) from exc
    return {"status": "ok", "entry": entry}


def _portfolio_payload(*, price_mode: str) -> dict[str, Any]:
    from application.portfolio_engine_service import PortfolioEngineService
    from application.portfolio_history_service import PortfolioHistoryService
    from application.portfolio_pnl_service import PortfolioPnlService
    from application.strategy_execution_service import StrategyExecutionService
    from application.strategy_history_service import StrategyHistoryService

    def _build() -> dict[str, Any]:
        entry_trigger_lab_service = _entry_trigger_lab_service(price_mode)
        execution_service = _strategy_execution_service(
            price_mode,
            entry_trigger_lab_service=entry_trigger_lab_service,
        )
        portfolio_engine_service = PortfolioEngineService(strategy_execution_service=execution_service)
        portfolio_pnl_service = PortfolioPnlService(portfolio_engine_service=portfolio_engine_service)

        execution_payload = execution_service.build_strategy_v1_execution_payload()
        portfolio_payload = portfolio_engine_service._build_portfolio_payload_from_execution(execution_payload)
        portfolio_pnl_payload = portfolio_pnl_service._build_portfolio_pnl_payload(
            portfolio_payload,
            portfolio_label="Strategy_v1 Weighted",
        )

        benchmark_execution_payload = execution_service.build_strategy_v1_execution_payload(
            pullback_pct_override=1.00,
            rule_label="Conservative Benchmark · Pullback 1.00%",
            is_shadow_benchmark=True,
        )
        benchmark_portfolio_payload = portfolio_engine_service._build_portfolio_payload_from_execution(
            benchmark_execution_payload
        )
        benchmark_portfolio_pnl_payload = portfolio_pnl_service._build_portfolio_pnl_payload(
            benchmark_portfolio_payload,
            portfolio_label="Conservative Benchmark Weighted",
        )

        return {
            "strategy_v1_execution": execution_payload,
            "strategy_v1_portfolio": portfolio_payload,
            "strategy_v1_benchmark_portfolio": benchmark_portfolio_payload,
            "strategy_v1_portfolio_pnl": portfolio_pnl_payload,
            "strategy_v1_benchmark_portfolio_pnl": benchmark_portfolio_pnl_payload,
            "strategy_v1_strategy_history": StrategyHistoryService(
                strategy_execution_service=execution_service
            ).build_strategy_v1_history_payload(execution_payload=execution_payload),
            "strategy_v1_portfolio_history": PortfolioHistoryService(
                portfolio_pnl_service=portfolio_pnl_service
            ).build_strategy_v1_history_payload(
                pnl_payload=portfolio_pnl_payload,
                benchmark_pnl_payload=benchmark_portfolio_pnl_payload,
            ),
        }

    return _build()


def _calibration_payload() -> dict[str, Any]:
    from application.calibration_service import CalibrationService

    return CalibrationService().build_dashboard_payload()


def _long_term_performance_payload() -> dict[str, Any]:
    from application.long_term_performance_service import LongTermPerformanceService

    return LongTermPerformanceService().build_dashboard_payload()


def _watchlist_payload() -> list[dict[str, str]]:
    from storage.repositories.watchlist_repository import load_watchlist

    return load_watchlist()


@app.on_event("startup")
def _startup() -> None:
    _bootstrap_database()


@app.get("/")
def root() -> dict[str, Any]:
    capabilities = api_capabilities_snapshot()
    payload = {
        "status": "ok",
        "service": "omnitrade-api",
        "message": "This is the API server.",
        "health_url": "/api/health",
        "capabilities_url": "/api/capabilities",
        "write_mode": capabilities["write_mode"],
    }
    if not is_production():
        payload["frontend_url"] = "http://127.0.0.1:3000/overview"
        payload["docs_url"] = "/docs"
    return payload


@app.get("/api/health")
def health() -> dict[str, Any]:
    _bootstrap_database()
    capabilities = api_capabilities_snapshot()
    return {
        "status": "ok",
        "service": "omnitrade-api",
        "data_seed_version": HOSTED_DATA_SEED_VERSION,
        "write_mode": capabilities["write_mode"],
        "user_mutations_enabled": capabilities["user_mutations_enabled"],
    }


@app.get("/api/capabilities")
def api_capabilities() -> dict[str, Any]:
    return api_capabilities_snapshot()


@app.get("/api/performance-lab")
async def performance_lab(
    price_mode: str = Query(
        default="cached",
        description="cached avoids live price refresh for frontend responsiveness; live matches Streamlit refresh behavior.",
    ),
) -> Any:
    normalized_price_mode = _validate_price_mode(price_mode)
    return await _run_service(
        "performance_lab",
        lambda: _cached_analytics_payload(
            "performance_lab",
            price_mode=normalized_price_mode,
            factory=lambda: _performance_payload(price_mode=normalized_price_mode),
        ),
    )


@app.post("/api/performance-log")
async def performance_log(payload: PerformanceLogMutation, request: Request) -> Any:
    _require_user_mutation("performance_log", request)

    def log_and_invalidate() -> dict[str, Any]:
        result = _log_performance_entry(payload)
        _ANALYTICS_RESPONSE_CACHE.invalidate()
        return result

    return await _run_service("performance_log", log_and_invalidate, timeout_seconds=15.0)


@app.get("/api/calibration")
async def calibration() -> Any:
    return await _run_service(
        "calibration",
        lambda: _cached_analytics_payload(
            "calibration",
            price_mode="resolved_outcomes",
            factory=_calibration_payload,
        ),
    )


@app.get("/api/long-term-performance")
async def long_term_performance() -> Any:
    return await _run_service("long_term_performance", _long_term_performance_payload)


@app.get("/api/portfolio")
async def portfolio(
    price_mode: str = Query(
        default="cached",
        description="cached avoids live price refresh for frontend responsiveness; live matches Streamlit refresh behavior.",
    ),
) -> Any:
    normalized_price_mode = _validate_price_mode(price_mode)
    return await _run_service(
        "portfolio",
        lambda: _cached_analytics_payload(
            "portfolio",
            price_mode=normalized_price_mode,
            factory=lambda: _portfolio_payload(price_mode=normalized_price_mode),
        ),
    )


@app.get("/api/ticker/{ticker}")
async def ticker_analysis(
    ticker: str,
    data_mode: str = Query(default=DATA_MODE_AUTO, description="auto, live, or demo"),
) -> Any:
    from application.ticker_service import (
        build_ticker_analysis,
        enrich_relative_strength_with_latest_scan,
    )

    normalized_mode = _validate_data_mode(data_mode)
    normalized_ticker = ticker.upper().strip()
    if not normalized_ticker:
        raise HTTPException(status_code=400, detail={"error": "invalid_ticker", "message": "Ticker is required."})

    payload = await _run_service(
        "ticker_analysis",
        lambda: enrich_relative_strength_with_latest_scan(
            build_ticker_analysis(normalized_ticker, data_mode=normalized_mode)
        ),
    )
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "ticker_not_found",
                "ticker": normalized_ticker,
                "message": "No ticker analysis is available for this symbol and data mode.",
            },
        )
    return payload


@app.get("/api/forecast/{ticker}")
async def kronos_forecast(
    ticker: str,
    horizon: int = Query(default=30, ge=1, le=120, description="Number of future trading days to forecast."),
    lookback: int = Query(default=400, ge=64, le=512, description="Historical daily bars sent to Kronos."),
    refresh: bool = Query(default=False, description="Bypass the cached forecast for this ticker and horizon."),
    entry_price: float | None = Query(default=None, gt=0),
    stop_loss_price: float | None = Query(default=None, gt=0),
    target_price: float | None = Query(default=None, gt=0),
) -> Any:
    """Read-only Kronos forecast. Never feeds scoring, recommendations, or the Performance Lab."""
    from application.kronos_forecast_service import build_forecast

    normalized_ticker = ticker.upper().strip()
    if not normalized_ticker:
        raise HTTPException(status_code=400, detail={"error": "invalid_ticker", "message": "Ticker is required."})

    def _build() -> dict[str, Any]:
        return build_forecast(
            normalized_ticker,
            horizon=horizon,
            lookback=lookback,
            refresh=refresh,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            target_price=target_price,
        )

    try:
        return await _run_service("kronos_forecast", _build, timeout_seconds=120.0)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        message = str(detail.get("message", ""))
        if exc.status_code == 500 and "Kronos" in message:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "kronos_unavailable",
                    "ticker": normalized_ticker,
                    "message": message,
                },
            ) from exc
        raise


@app.get("/api/forecast-health")
def kronos_forecast_health() -> Any:
    from providers.forecast.kronos_client import KronosUnavailable, health, kronos_enabled

    if not kronos_enabled():
        return {"enabled": False, "status": "disabled", "message": "Kronos forecasting is disabled for this deployment."}
    try:
        payload = {"enabled": True, "status": "ok", **health()}
        payload.pop("service_url", None)
        return payload
    except KronosUnavailable:
        return {"enabled": True, "status": "unavailable", "message": "Forecast service is unavailable."}


@app.get("/api/watchlist")
def watchlist() -> Any:
    return _json_response(_watchlist_payload())


@app.post("/api/watchlist")
def add_watchlist_item(payload: WatchlistMutation, request: Request) -> Any:
    _require_user_mutation("watchlist_add", request)
    from storage.repositories.watchlist_repository import add_to_watchlist

    ticker = payload.ticker.upper().strip()
    if not ticker:
        raise HTTPException(status_code=400, detail={"error": "invalid_ticker", "message": "Ticker is required."})
    add_to_watchlist(ticker, payload.source)
    return _json_response({"status": "ok", "watchlist": _watchlist_payload()})


@app.delete("/api/watchlist/{ticker}")
def delete_watchlist_item(ticker: str, request: Request) -> Any:
    _require_user_mutation("watchlist_delete", request)
    from storage.repositories.watchlist_repository import remove_from_watchlist

    normalized_ticker = ticker.upper().strip()
    if not normalized_ticker or len(normalized_ticker) > 12 or not all(
        ch.isalnum() or ch in ".-" for ch in normalized_ticker
    ):
        raise HTTPException(status_code=400, detail={"error": "invalid_ticker", "message": "Ticker is required."})
    remove_from_watchlist(normalized_ticker)
    return _json_response({"status": "ok", "watchlist": _watchlist_payload()})


@app.get("/api/overview")
async def overview(
    request: Request,
    refresh: bool = Query(default=False, description="Run a fresh scan instead of returning cached overview data."),
    data_mode: str = Query(default=DATA_MODE_AUTO, description="auto, live, or demo"),
    universe: str = Query(default="global", description="global or international"),
) -> Any:
    if refresh:
        enforce_rate_limit(request, bucket="refresh", limit=REFRESH_RATE_LIMIT)
    normalized_mode = _validate_data_mode(data_mode)
    universe_key = universe.strip().lower()
    try:
        return await _run_service(
            "overview",
            lambda: _load_overview_payload(refresh=refresh, data_mode=normalized_mode, universe_key=universe_key),
        )
    except HTTPException as exc:
        if exc.status_code != 504:
            raise
        return await _run_service(
            "overview_fallback",
            lambda: _load_overview_fallback_payload(
                universe_key=universe_key,
                reason="The live overview scan timed out.",
            ),
            timeout_seconds=30.0,
        )


@app.get("/api/overview/refresh-status")
async def overview_refresh_status(
    universe: str = Query(default="global", description="global or international"),
) -> Any:
    universe_key = universe.strip().lower()
    _overview_universe_config(universe_key)
    return await _run_service(
        "overview_refresh_status",
        lambda: _load_overview_refresh_status(universe_key=universe_key),
        timeout_seconds=10.0,
    )


__all__ = ["app"]
