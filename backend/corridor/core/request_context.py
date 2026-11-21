"""Correlation IDs shared by HTTP, Celery and Channels."""

from __future__ import annotations

import re
import uuid

import structlog

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def new_request_id() -> str:
    return uuid.uuid4().hex


def accept_or_generate(incoming: str | None) -> str:
    """Accept a client/ALB supplied request id only if it is well formed (no log injection)."""
    if incoming and _VALID_REQUEST_ID.fullmatch(incoming):
        return incoming
    return new_request_id()


def current_request_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("request_id")
    return str(value) if value is not None else None


def bind_request_id(request_id: str) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        import sentry_sdk

        sentry_sdk.get_isolation_scope().set_tag("request_id", request_id)
    except Exception:  # noqa: S110  # sentry is optional; logging must never break requests
        pass
