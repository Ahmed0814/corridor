"""Sentry initialisation with PII scrubbing."""

from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from corridor.core.logging import REDACT_KEYS, REDACTED


def _scrub(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: (REDACTED if str(k).lower() in REDACT_KEYS else _scrub(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_scrub(v) for v in data]
    return data


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        if "headers" in request:
            request["headers"] = _scrub(request["headers"])
        if "data" in request:
            request["data"] = _scrub(request["data"])
    if "extra" in event:
        event["extra"] = _scrub(event["extra"])
    return event


def init_sentry(dsn: str, environment: str, release: str, transport: Any = None) -> None:
    options: dict[str, Any] = {
        "dsn": dsn,
        "environment": environment,
        "release": release,
        # Error logs become breadcrumbs, not events: exceptions are captured once, by the
        # Django/Celery integrations or by the API's unhandled-exception handler.
        "integrations": [
            DjangoIntegration(),
            CeleryIntegration(),
            LoggingIntegration(level=logging.INFO, event_level=None),
        ],
        "traces_sample_rate": 0.0,  # tracing off for the free tier; errors only
        # Explicit, strict collection policy (security-model.md §7). Local variables in stack
        # frames, bodies, cookies and query strings can carry PII or tracking tokens.
        "data_collection": {
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {
                "request": {"mode": "allowlist", "terms": ["user-agent", "x-request-id", "accept-language"]}
            },
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "database_query_data": False,
            "queues": False,
            "stack_frame_variables": False,
        },
        "before_send": before_send,
    }
    if transport is not None:
        options["transport"] = transport
    sentry_sdk.init(**options)
