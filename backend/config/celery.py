"""Celery application (broker: Amazon SQS; ElasticMQ locally) — DECISIONS D-009, D-031."""

from __future__ import annotations

import os
from typing import Any

import structlog
from celery import Celery, signals

from corridor.core.request_context import bind_request_id, current_request_id, new_request_id

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("corridor")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={"corridor.events.*": {"queue": "events"}},
    worker_hijack_root_logger=False,  # keep our structlog configuration
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # Phase 1: proves beat → SQS → worker end to end. Real jobs (outbox relay,
        # freshness sweep, partitions, retention) are added in later phases.
        "heartbeat": {"task": "corridor.events.tasks.heartbeat", "schedule": 60.0},
        # Transactional outbox -> SQS (D-014, D-051). Business events, not GPS.
        "relay-outbox": {"task": "corridor.events.tasks.relay_outbox", "schedule": 5.0},
        # GPS partitions ahead + retention archive (drops need approval, D-058).
        "gps-maintenance": {"task": "corridor.tracking.tasks.gps_maintenance", "schedule": 86400.0},
    },
)
app.autodiscover_tasks()

log = structlog.get_logger("corridor.celery")


@signals.before_task_publish.connect
def _propagate_request_id(headers: dict[str, Any] | None = None, **_: Any) -> None:
    if headers is not None:
        headers.setdefault("request_id", current_request_id() or new_request_id())


@signals.task_prerun.connect
def _bind_task_context(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    structlog.contextvars.clear_contextvars()
    request_id = getattr(task.request, "request_id", None) if task is not None else None
    bind_request_id(request_id or new_request_id())
    structlog.contextvars.bind_contextvars(task_id=task_id, task_name=getattr(task, "name", None))


@signals.task_postrun.connect
def _clear_task_context(**_: Any) -> None:
    structlog.contextvars.clear_contextvars()
