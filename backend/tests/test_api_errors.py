"""The uniform error envelope (MASTER_PROMPT §5)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import structlog
from django.http import Http404, HttpRequest, HttpResponse
from django.test import Client, RequestFactory
from ninja.errors import HttpError, ValidationError

from corridor.core.api import api

pytestmark = pytest.mark.django_db  # ATOMIC_REQUESTS


@pytest.fixture
def request_with_id() -> Iterator[HttpRequest]:
    structlog.contextvars.bind_contextvars(request_id="envelope-test-0001")
    yield RequestFactory().get("/api/v1/anything")
    structlog.contextvars.clear_contextvars()


def _body(response: HttpResponse) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(response.content)
    return body


def test_meta_endpoint() -> None:
    response = Client().get("/api/v1/meta")
    assert response.status_code == 200
    assert response.json()["api_version"] == "v1"


def test_openapi_schema_is_served() -> None:
    response = Client().get("/api/v1/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Corridor API"


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (ValidationError([{"loc": ["body", "x"], "msg": "bad"}]), 422, "validation_error"),
        (Http404(), 404, "not_found"),
        (HttpError(409, "already dispatched"), 409, "conflict"),
        (HttpError(403, "nope"), 403, "forbidden"),
        (RuntimeError("boom"), 500, "internal_error"),
    ],
)
def test_error_envelope(request_with_id: HttpRequest, exc: Exception, status: int, code: str) -> None:
    response = api.on_exception(request_with_id, exc)
    assert response.status_code == status
    body = _body(response)
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["request_id"] == "envelope-test-0001"
    assert set(body["error"]) == {"code", "message", "details", "request_id"}


def test_internal_error_does_not_leak_exception_text(request_with_id: HttpRequest) -> None:
    response = api.on_exception(request_with_id, RuntimeError("password=hunter2 in stack"))
    assert "hunter2" not in response.content.decode()
