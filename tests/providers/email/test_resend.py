from __future__ import annotations

import io
import json
from urllib import error

from domain.alerts.models import RenderedMessage
from providers.email import resend
from providers.email.resend import RESEND_URL, ResendClient


def test_resend_posts_json_with_the_idempotency_key() -> None:
    captured: dict = {}

    def transport(url, headers, body):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        return 200, {"id": "msg_123"}

    result = ResendClient("re_test", transport=transport).send(_message())

    assert result.message_id == "msg_123"
    assert result.retryable is False
    assert captured["url"] == RESEND_URL
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["headers"]["Idempotency-Key"] == "urgent|NVDA|short_term_day|ENTER NOW|2026-10-14|alerts_v1"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["body"]["from"] == "OmniTrade research <alerts@example.com>"
    assert captured["body"]["to"] == ["operator@example.com"]
    assert captured["body"]["subject"] == "OmniTrade review: NVDA exceptional setup"
    json.dumps(captured["body"])


def test_resend_treats_timeout_as_retryable_and_client_errors_as_final() -> None:
    def timeout_transport(url, headers, body):
        raise TimeoutError("timed out")

    def client_error(url, headers, body):
        return 422, {"message": "invalid_from"}

    def server_error(url, headers, body):
        return 503, {"message": "unavailable"}

    timeout = ResendClient("re_test", transport=timeout_transport).send(_message())
    rejected = ResendClient("re_test", transport=client_error).send(_message())
    unavailable = ResendClient("re_test", transport=server_error).send(_message())

    assert timeout.retryable is True
    assert timeout.message_id is None
    assert rejected.retryable is False
    assert rejected.error == "invalid_from"
    assert unavailable.retryable is True


def test_urllib_http_error_is_returned_as_a_status(monkeypatch) -> None:
    def explode(outgoing, timeout):
        raise error.HTTPError(
            RESEND_URL,
            400,
            "bad request",
            hdrs=None,
            fp=io.BytesIO(b'{"message":"bad request"}'),
        )

    monkeypatch.setattr(resend.request, "urlopen", explode)
    status, payload = resend.urllib_transport(RESEND_URL, {}, {"text": "hello"})
    assert status == 400
    assert payload["message"] == "bad request"


def _message() -> RenderedMessage:
    return RenderedMessage(
        sender="OmniTrade research <alerts@example.com>",
        recipients=("operator@example.com",),
        subject="OmniTrade review: NVDA exceptional setup",
        text="Decision support, not financial advice, and not a broker.",
        dedupe_key="urgent|NVDA|short_term_day|ENTER NOW|2026-10-14|alerts_v1",
    )
