"""HTTP adapter for the Kronos forecasting sidecar.

The Kronos foundation model (PyTorch) intentionally lives outside this service.
This module only speaks JSON over HTTP so the API deployment keeps its light
dependency set. Uses the standard library so no new packages are required.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0


class KronosUnavailable(RuntimeError):
    """Raised when the Kronos sidecar cannot be reached or returns an error."""


@dataclass(frozen=True)
class KronosCandle:
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass(frozen=True)
class KronosForecast:
    model: str
    generated_at: str | None
    points: list[dict[str, Any]]
    bands: dict[str, list[float]] | None


def kronos_service_url() -> str:
    return os.environ.get("KRONOS_SERVICE_URL", "").strip().rstrip("/")


def kronos_enabled() -> bool:
    flag = os.environ.get("KRONOS_ENABLED", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    # Default: enabled as soon as a service URL is configured.
    return bool(kronos_service_url())


def _timeout_seconds() -> float:
    try:
        return float(os.environ.get("KRONOS_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = kronos_service_url()
    if not base:
        raise KronosUnavailable("KRONOS_SERVICE_URL is not configured.")

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(request, timeout=_timeout_seconds()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise KronosUnavailable(f"Kronos service returned {exc.code}: {detail}") from exc
        except Exception as exc:  # network error, timeout, malformed JSON
            last_error = exc
            log.warning("Kronos request attempt %s failed: %s", attempt, exc)

    raise KronosUnavailable(f"Kronos service is unreachable: {last_error}")


def health() -> dict[str, Any]:
    base = kronos_service_url()
    if not base:
        raise KronosUnavailable("KRONOS_SERVICE_URL is not configured.")
    try:
        with urllib.request.urlopen(f"{base}/health", timeout=10.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise KronosUnavailable(f"Kronos service is unreachable: {exc}") from exc


def predict(
    *,
    candles: list[dict[str, Any]],
    future_timestamps: list[str],
    temperature: float = 1.0,
    top_p: float = 0.9,
    sample_count: int = 20,
) -> KronosForecast:
    payload = {
        "candles": candles,
        "future_timestamps": future_timestamps,
        "horizon": len(future_timestamps),
        "T": temperature,
        "top_p": top_p,
        "sample_count": sample_count,
    }
    raw = _post("/predict", payload)
    points = raw.get("points")
    if not isinstance(points, list) or not points:
        raise KronosUnavailable("Kronos service returned no forecast points.")
    bands = raw.get("bands") if isinstance(raw.get("bands"), dict) else None
    return KronosForecast(
        model=str(raw.get("model", "kronos")),
        generated_at=raw.get("generated_at"),
        points=points,
        bands=bands,
    )


__all__ = [
    "KronosCandle",
    "KronosForecast",
    "KronosUnavailable",
    "health",
    "kronos_enabled",
    "kronos_service_url",
    "predict",
]
