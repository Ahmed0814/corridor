"""Tenant context: the single way code tells PostgreSQL which tenant and user it acts for.

MASTER_PROMPT §4.4 and docs/security/security-model.md §4.2:

* Values are set with ``set_config(name, value, true)``, which is ``SET LOCAL``: they vanish at
  commit or rollback, so a pooled connection can never carry one request's tenant into the next.
  A session-level SET of the app.* settings is forbidden (a test greps for it).
* The same helper is used by HTTP requests (inside the ATOMIC_REQUESTS transaction), Celery
  tasks (``core.tasks.tenant_task``) and Channels consumers.
* A ContextVar mirrors the database setting so the scoped ORM manager can filter in Python and
  fail loudly when no tenant is set. RLS remains the backstop if application code is wrong.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, ClassVar, Self

from django.db import connections, models, transaction


class TenantContextError(RuntimeError):
    """Raised when tenant-owned data is touched without a tenant context."""


@dataclass(frozen=True, slots=True)
class DbContext:
    tenant_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    user_sub: str | None = None


_EMPTY = DbContext()
_current: ContextVar[DbContext] = ContextVar("corridor_db_context", default=_EMPTY)


def current_context() -> DbContext:
    return _current.get()


def current_tenant_id() -> uuid.UUID | None:
    return _current.get().tenant_id


def require_tenant_id() -> uuid.UUID:
    tenant_id = _current.get().tenant_id
    if tenant_id is None:
        raise TenantContextError("No tenant context is set for this operation.")
    return tenant_id


def _write(ctx: DbContext, using: str) -> None:
    conn = connections[using]
    if not conn.in_atomic_block:
        # SET LOCAL outside a transaction is a no-op in PostgreSQL: refuse instead of silently
        # running without isolation.
        raise TenantContextError("Tenant context must be applied inside a transaction.")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true), "
            "set_config('app.user_id', %s, true), "
            "set_config('app.user_sub', %s, true)",
            [
                str(ctx.tenant_id) if ctx.tenant_id else "",
                str(ctx.user_id) if ctx.user_id else "",
                ctx.user_sub or "",
            ],
        )


def apply_context(
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    user_sub: str | None = None,
    using: str = "default",
) -> DbContext:
    """Set the context for the rest of the current transaction (no automatic restore).

    Used by request authentication, where the transaction is the request itself.
    """
    ctx = DbContext(tenant_id=tenant_id, user_id=user_id, user_sub=user_sub)
    _write(ctx, using)
    _current.set(ctx)
    return ctx


@contextmanager
def tenant_context(
    tenant_id: uuid.UUID | None,
    *,
    user_id: uuid.UUID | None = None,
    user_sub: str | None = None,
    using: str = "default",
) -> Iterator[DbContext]:
    """Run a block in its own transaction (or savepoint) bound to one tenant.

    On exit the previous context is restored, both in Python and in the database, so nested
    use (e.g. an eager Celery task inside a request in tests) cannot leak a tenant outward.
    """
    previous = _current.get()
    ctx = DbContext(tenant_id=tenant_id, user_id=user_id, user_sub=user_sub)
    with transaction.atomic(using=using):
        token = _current.set(ctx)
        try:
            _write(ctx, using)
            yield ctx
        finally:
            _current.reset(token)
            conn = connections[using]
            if conn.in_atomic_block and not conn.needs_rollback:
                _write(previous, using)


def clear_context() -> None:
    """Forget the Python-side context (the DB side ends with the transaction)."""
    _current.set(_EMPTY)


# --------------------------------------------------------------------------- ORM base


class TenantScopedQuerySet(models.QuerySet[Any]):
    pass


class TenantScopedManager(models.Manager[Any]):
    """Default manager of every tenant-owned model: filters by the context tenant, or raises."""

    use_in_migrations = False

    def get_queryset(self) -> models.QuerySet[Any]:
        return super().get_queryset().filter(tenant_id=require_tenant_id())


class TenantOwnedModel(models.Model):
    """Base for every tenant-owned table (RLS policy added by core.db.tenant_rls()).

    ``tenant`` is never settable from client input: it is filled from the context on insert
    and a mismatch raises.
    """

    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, editable=False, related_name="+", db_index=True
    )

    objects: ClassVar[TenantScopedManager] = TenantScopedManager()

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        tenant_id = require_tenant_id()
        if self.tenant_id is None:
            self.tenant_id = tenant_id
        elif self.tenant_id != tenant_id:
            raise TenantContextError("Refusing to save a row that belongs to another tenant.")
        super().save(*args, **kwargs)

    @classmethod
    def for_context(cls, **kwargs: Any) -> Self:
        return cls(tenant_id=require_tenant_id(), **kwargs)
