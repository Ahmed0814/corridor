"""Celery helpers shared by all modules.

``tenant_task`` is the only way to write a task that touches tenant data
(security-model.md §4.2). The tenant id is the task's first argument and must come from
server-side state (an outbox row, a validated RequestContext), never from client input. The
body runs inside ``tenant_context()``: its own transaction with SET LOCAL app.tenant_id, so RLS
and the scoped managers apply exactly as in a request.
"""

from __future__ import annotations

import functools
import uuid
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

import structlog
from celery import shared_task

from corridor.core.tenancy import tenant_context

P = ParamSpec("P")
R = TypeVar("R")


def tenant_task(*task_args: Any, **task_options: Any) -> Callable[[Callable[P, R]], Any]:
    def decorator(fn: Callable[P, R]) -> Any:
        @functools.wraps(fn)
        def run(tenant_id: str, *args: P.args, **kwargs: P.kwargs) -> R:
            tid = uuid.UUID(str(tenant_id))  # raises on garbage: never run without a valid tenant
            structlog.contextvars.bind_contextvars(tenant_id=str(tid))
            with tenant_context(tid):
                return fn(*args, **kwargs)

        return shared_task(*task_args, **task_options)(run)

    return decorator
