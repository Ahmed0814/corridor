from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator

import pytest
import structlog
from django.test import Client

from corridor.core.logging import REDACTED, redact_sensitive

pytestmark = pytest.mark.django_db  # ATOMIC_REQUESTS: every API request opens a transaction


@pytest.fixture
def log_output() -> Iterator[io.StringIO]:
    """Redirect the root structured handler into a buffer for the duration of a test."""
    handler = logging.getLogger().handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    buffer = io.StringIO()
    previous = handler.setStream(buffer)
    try:
        yield buffer
    finally:
        handler.setStream(previous)


def _json_lines(text: str) -> list[dict[str, object]]:
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if raw.startswith("{"):
            lines.append(json.loads(raw))
    return lines


def test_response_carries_generated_request_id() -> None:
    response = Client().get("/healthz/live")
    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32


def test_valid_incoming_request_id_is_kept() -> None:
    response = Client().get("/healthz/live", headers={"X-Request-ID": "alb-trace-12345678"})
    assert response.headers["X-Request-ID"] == "alb-trace-12345678"


@pytest.mark.parametrize("bad", ["short", "has space in it 1234", "inject\nnewline-123456", "x" * 200])
def test_malformed_request_id_is_replaced(bad: str) -> None:
    response = Client().get("/healthz/live", HTTP_X_REQUEST_ID=bad)
    assert response.headers["X-Request-ID"] != bad
    assert len(response.headers["X-Request-ID"]) == 32


def test_access_log_is_json_with_request_id(log_output: io.StringIO) -> None:
    response = Client().get("/api/v1/meta", headers={"X-Request-ID": "corr-abcdef123456"})
    assert response.status_code == 200
    err = log_output.getvalue()
    access = [line for line in _json_lines(err) if line.get("event") == "http_request"]
    assert access, f"no JSON access log line found in: {err!r}"
    line = access[-1]
    assert line["request_id"] == "corr-abcdef123456"
    assert line["path"] == "/api/v1/meta"
    assert line["status"] == 200
    assert line["level"] == "info"
    assert "timestamp" in line


def test_stdlib_loggers_are_rendered_as_json(log_output: io.StringIO) -> None:
    structlog.contextvars.bind_contextvars(request_id="stdlib-bridge-0001")
    try:
        logging.getLogger("django.request").warning("plain stdlib message")
    finally:
        structlog.contextvars.clear_contextvars()
    err = log_output.getvalue()
    lines = [line for line in _json_lines(err) if line.get("event") == "plain stdlib message"]
    assert lines and lines[0]["request_id"] == "stdlib-bridge-0001"


def test_sensitive_keys_are_redacted() -> None:
    event = {
        "event": "x",
        "authorization": "Bearer abc",
        "phone_e164": "+25377000000",
        "headers": {"Authorization": "Bearer abc", "Accept": "json"},
        "keep": "visible",
    }
    out = redact_sensitive(None, "info", event)
    assert out["authorization"] == REDACTED
    assert out["phone_e164"] == REDACTED
    assert out["headers"] == {"Authorization": REDACTED, "Accept": "json"}
    assert out["keep"] == "visible"
