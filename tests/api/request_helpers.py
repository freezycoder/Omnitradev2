from __future__ import annotations

from starlette.requests import Request


def fake_request(*, headers: dict[str, str] | None = None, host: str = "127.0.0.1") -> Request:
    encoded = [(key.lower().encode(), value.encode()) for key, value in (headers or {}).items()]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": encoded,
        "client": (host, 12345),
        "server": ("127.0.0.1", 80),
    }
    return Request(scope)
