"""Sentry wiring: errors are captured, tagged with request_id, and scrubbed.

Uses an in-memory transport — no network, no real DSN (MASTER_PROMPT §0.5).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
import structlog
from django.test import RequestFactory
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from corridor.core.api import api
from corridor.core.request_context import bind_request_id
from corridor.core.sentry import before_send, init_sentry


class MemoryTransport(Transport):
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[Any] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


@pytest.fixture
def transport() -> Iterator[MemoryTransport]:
    t = MemoryTransport()
    init_sentry(dsn="https://public@sentry.invalid/1", environment="test", release="t", transport=t)
    yield t
    sentry_sdk.init()  # disable again
    structlog.contextvars.clear_contextvars()


def test_unhandled_api_error_reaches_sentry_with_request_id(transport: MemoryTransport) -> None:
    with sentry_sdk.isolation_scope():
        bind_request_id("sentry-corr-000001")
        request = RequestFactory().get("/api/v1/x", HTTP_AUTHORIZATION="Bearer secret-token")
        api.on_exception(request, RuntimeError("kaboom"))
    sentry_sdk.flush()
    assert len(transport.events) == 1
    event = transport.events[0]
    assert event["tags"]["request_id"] == "sentry-corr-000001"
    assert event["environment"] == "test"
    assert event["exception"]["values"][-1]["value"] == "kaboom"


def test_before_send_scrubs_headers_body_and_cookies() -> None:
    event = {
        "request": {
            "headers": {"Authorization": "Bearer x", "User-Agent": "ua"},
            "cookies": {"session": "abc"},
            "data": {"password": "p", "plate": "DJ-1"},
        },
        "extra": {"token": "t"},
    }
    out = before_send(event, {})
    assert out is not None
    assert out["request"]["headers"]["Authorization"] == "[redacted]"
    assert out["request"]["headers"]["User-Agent"] == "ua"
    assert "cookies" not in out["request"]
    assert out["request"]["data"] == {"password": "[redacted]", "plate": "DJ-1"}
    assert out["extra"] == {"token": "[redacted]"}


def test_strict_data_collection_policy_is_applied(transport: MemoryTransport) -> None:
    resolved = sentry_sdk.get_client().options["data_collection"]
    assert resolved["user_info"] is False
    assert resolved["cookies"]["mode"] == "off"
    assert resolved["url_query_params"]["mode"] == "off"
    assert resolved["http_headers"]["request"]["mode"] == "allowlist"
    assert "authorization" not in resolved["http_headers"]["request"].get("terms", [])
    assert resolved["http_bodies"] == []
    assert resolved["stack_frame_variables"] is False
