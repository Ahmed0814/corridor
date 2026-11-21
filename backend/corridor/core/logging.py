"""Structured logging (structlog) with a stdlib bridge.

Every log line — ours, Django's, Celery's — is rendered by the same processor chain, so
production output is one JSON object per line carrying request_id / task_id context.
"""

from __future__ import annotations

import logging
import logging.config
from collections.abc import MutableMapping
from typing import Any

import structlog

REDACT_KEYS = frozenset(
    {
        "authorization",
        "password",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "secret",
        "phone",
        "phone_e164",
        "license_number",
        "signature",
        "cookie",
    }
)
REDACTED = "[redacted]"


def redact_sensitive(_: Any, __: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Replace values of sensitive keys (top level and one nested level) before rendering."""
    for key, value in list(event_dict.items()):
        if key.lower() in REDACT_KEYS:
            event_dict[key] = REDACTED
        elif isinstance(value, dict):
            event_dict[key] = {
                k: (REDACTED if str(k).lower() in REDACT_KEYS else v) for k, v in value.items()
            }
    return event_dict


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    renderer: Any = (
        structlog.dev.ConsoleRenderer() if fmt == "console" else structlog.processors.JSONRenderer()
    )
    shared = _shared_processors()

    structlog.configure(
        processors=[
            *shared,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "structured": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processors": [
                        structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.processors.format_exc_info,
                        renderer,
                    ],
                    "foreign_pre_chain": shared,
                }
            },
            "handlers": {
                "default": {"class": "logging.StreamHandler", "formatter": "structured"},
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                # Our own access log replaces these.
                "django.server": {"level": "WARNING"},
                "uvicorn.access": {"level": "WARNING"},
                "daphne.access": {"level": "WARNING"},
                "botocore": {"level": "WARNING"},
            },
        }
    )
