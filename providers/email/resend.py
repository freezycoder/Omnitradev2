"""Resend HTTPS client. The transport is injectable so tests stay offline."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib import error, request

from domain.alerts.models import RenderedMessage, SendResult


RESEND_URL = "https://api.resend.com/emails"
Transport = Callable[[str, dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]]


class ResendClient:
    def __init__(self, api_key: str, transport: Transport | None = None) -> None:
        self.api_key = api_key
        self.transport = transport or urllib_transport

    def send(self, message: RenderedMessage) -> SendResult:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": message.dedupe_key,
            "User-Agent": "OmniTrade-Alerts/1.0",
        }
        body = {
            "from": message.sender,
            "to": list(message.recipients),
            "subject": message.subject,
            "text": message.text,
        }
        try:
            status, payload = self.transport(RESEND_URL, headers, body)
        except TimeoutError as exc:
            return SendResult(message_id=None, retryable=True, error=str(exc) or "timeout")
        except error.URLError as exc:
            return SendResult(message_id=None, retryable=True, error=str(exc.reason))
        if 200 <= status < 300:
            message_id = payload.get("id")
            if isinstance(message_id, str) and message_id:
                return SendResult(message_id=message_id, retryable=False)
            return SendResult(message_id=None, retryable=False, error="missing_message_id")
        detail = _error_detail(payload) or f"http_{status}"
        return SendResult(message_id=None, retryable=status >= 500, error=detail)


def urllib_transport(url: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    encoded = json.dumps(body).encode("utf-8")
    outgoing = request.Request(url, data=encoded, headers=headers, method="POST")
    try:
        with request.urlopen(outgoing, timeout=15) as response:
            return response.status, _read_json(response.read())
    except error.HTTPError as exc:
        return exc.code, _read_json(exc.read())


def _read_json(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"message": raw.decode("utf-8", errors="replace")}
    if isinstance(parsed, dict):
        return parsed
    return {"message": str(parsed)}


def _error_detail(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message.strip():
        return message.strip()
    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""
