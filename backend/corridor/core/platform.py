"""The audited Platform Super Admin path (DECISIONS D-007, MASTER_PROMPT §4.4).

The ``platform`` database alias logs in as ``corridor_platform``, which has its own
``platform_all`` RLS policies on a few tables. Ordinary code must never use it, so every query on
that alias is refused unless it runs inside ``platform_session()``, which requires a named actor
and a reason that the caller records in the audit log.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created
from django.dispatch import receiver

PLATFORM_DB = "platform"


class PlatformAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PlatformActor:
    user_id: uuid.UUID | None  # None only for operator CLI commands (actor recorded as "system")
    reason: str


_actor: ContextVar[PlatformActor | None] = ContextVar("corridor_platform_actor", default=None)


def current_platform_actor() -> PlatformActor | None:
    return _actor.get()


@contextmanager
def platform_session(actor: PlatformActor) -> Iterator[PlatformActor]:
    if not actor.reason.strip():
        raise PlatformAccessError("A platform session needs a reason.")
    token = _actor.set(actor)
    try:
        with transaction.atomic(using=PLATFORM_DB):
            yield actor
    finally:
        _actor.reset(token)


# Transaction control issued by Django itself (atomic blocks, test teardown). Reads no data.
_TRANSACTION_CONTROL = ("SAVEPOINT ", "RELEASE SAVEPOINT ", "ROLLBACK TO SAVEPOINT ", "SET CONSTRAINTS ALL ")


def _guard(execute: Callable[..., Any], sql: str, params: Any, many: bool, context: Any) -> Any:
    if _actor.get() is None and not sql.lstrip().upper().startswith(_TRANSACTION_CONTROL):
        raise PlatformAccessError("The platform database alias is only usable inside platform_session().")
    return execute(sql, params, many, context)


@receiver(connection_created)
def _install_guard(sender: Any, connection: BaseDatabaseWrapper, **_: Any) -> None:
    if connection.alias == PLATFORM_DB and _guard not in connection.execute_wrappers:
        connection.execute_wrappers.append(_guard)


class DefaultOnlyRouter:
    """Ordinary ORM calls always use ``default``. ``platform`` must be named explicitly."""

    def db_for_read(self, model: type[Any], **hints: Any) -> str:
        return "default"

    def db_for_write(self, model: type[Any], **hints: Any) -> str:
        return "default"

    def allow_relation(self, obj1: Any, obj2: Any, **hints: Any) -> bool:
        return True

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool:
        return db == "default"
