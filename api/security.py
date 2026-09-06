"""HTTP security controls that do not invent a user-account system.

OmniTrade has no passwords or sessions. Hosted deployments stay read-only.
These helpers add headers, optional write-token checks, rate limits, HTTPS
redirects, and production-safe error payloads.
"""

from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp


WRITE_TOKEN_ENV = "OMNITRADE_WRITE_TOKEN"
WRITE_TOKEN_HEADER = "x-omnitrade-write-token"
MUTATION_RATE_LIMIT = int(os.environ.get("OMNITRADE_MUTATION_RATE_LIMIT", "20"))
REFRESH_RATE_LIMIT = int(os.environ.get("OMNITRADE_REFRESH_RATE_LIMIT", "6"))
RATE_WINDOW_SECONDS = 60.0

_RATE_LOCK = Lock()
_RATE_BUCKETS: dict[tuple[str, str], Deque[float]] = defaultdict(deque)


def is_production(environment: str | None = None) -> bool:
    active = (environment or os.environ.get("ENV", "production")).strip().lower()
    return active == "production"


def public_error_message(exc: BaseException, *, environment: str | None = None) -> str:
    """Never send raw exception text to hosted clients."""
    if is_production(environment):
        return "The service failed. See server logs for details."
    return str(exc)


def configured_write_token() -> str:
    return os.environ.get(WRITE_TOKEN_ENV, "").strip()


def enforce_write_token(request: Request) -> None:
    expected = configured_write_token()
    if not expected:
        return
    provided = (request.headers.get(WRITE_TOKEN_HEADER) or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "write_token_required",
                "message": "Mutations require a valid X-OmniTrade-Write-Token header.",
            },
        )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(request: Request, *, bucket: str, limit: int | None = None) -> None:
    max_events = limit if limit is not None else MUTATION_RATE_LIMIT
    key = (bucket, _client_ip(request))
    now = time.monotonic()
    with _RATE_LOCK:
        events = _RATE_BUCKETS[key]
        while events and now - events[0] > RATE_WINDOW_SECONDS:
            events.popleft()
        if len(events) >= max_events:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limited",
                    "message": "Too many requests. Wait a minute and try again.",
                },
            )
        events.append(now)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        if is_production() and _should_redirect_https(request):
            https_url = request.url.replace(scheme="https")
            return RedirectResponse(str(https_url), status_code=308)

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        if is_production() and _request_is_https(request):
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


def _request_is_https(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    return proto == "https"


def _should_redirect_https(request: Request) -> bool:
    host = (request.headers.get("host") or request.url.hostname or "").split(":")[0]
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    return proto == "http"


__all__ = [
    "REFRESH_RATE_LIMIT",
    "SecurityHeadersMiddleware",
    "WRITE_TOKEN_HEADER",
    "configured_write_token",
    "enforce_rate_limit",
    "enforce_write_token",
    "is_production",
    "public_error_message",
]
