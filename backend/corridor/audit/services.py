"""audit public interface. Other modules may import only this file and schemas.py (D-005)."""

from __future__ import annotations

import uuid
from typing import Any

from corridor.audit.models import AuditLog
from corridor.audit.schemas import AuditEntry
from corridor.core.request_context import current_client, current_request_id

# Action names used across modules (one place, so reports and tests agree).
LOGIN = "auth.login"
TENANT_SWITCHED = "tenant.switched"
TENANT_CREATED = "tenant.created"
TENANT_SUSPENDED = "tenant.suspended"
TENANT_ACTIVATED = "tenant.activated"
TENANT_SETTINGS_CHANGED = "tenant.settings_changed"
MEMBERSHIP_INVITED = "membership.invited"
MEMBERSHIP_ACTIVATED = "membership.activated"
MEMBERSHIP_SUSPENDED = "membership.suspended"
MEMBERSHIP_REACTIVATED = "membership.reactivated"
ROLE_CHANGED = "role.changed"
PLATFORM_READ = "platform.read"

ActorKind = AuditLog.ActorKind


def record(
    action: str,
    *,
    tenant_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    actor_kind: str = ActorKind.USER,
    target_type: str = "",
    target_id: str | uuid.UUID = "",
    metadata: dict[str, Any] | None = None,
    using: str = "default",
) -> int:
    """Append one audit row in the caller's transaction. Returns its id.

    On the default alias RLS only accepts rows for the current tenant, or tenant-less rows about
    the current user. The platform alias may write any row (inside platform_session()).
    """
    ip, user_agent = current_client()
    row = AuditLog.objects.using(using).create(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        actor_kind=actor_kind,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata=metadata or {},
        request_id=current_request_id() or "",
        ip_address=ip,
        user_agent=user_agent,
    )
    return row.id


def list_entries(
    *, tenant_id: uuid.UUID, limit: int, offset: int, action: str | None = None
) -> list[AuditEntry]:
    """Audit rows of the current tenant, newest first (RLS also restricts to that tenant)."""
    qs = AuditLog.objects.filter(tenant_id=tenant_id).order_by("-occurred_at", "-id")
    if action:
        qs = qs.filter(action=action)
    return [_entry(row) for row in qs[offset : offset + limit]]


def entries_for_tests(*, using: str = "default", **filters: Any) -> list[AuditEntry]:
    """Read helper for tests and platform tooling (still subject to the alias' RLS)."""
    return [_entry(row) for row in AuditLog.objects.using(using).filter(**filters).order_by("id")]


def _entry(row: AuditLog) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        tenant_id=row.tenant_id,
        actor_user_id=row.actor_user_id,
        actor_kind=row.actor_kind,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        metadata=row.metadata,
        request_id=row.request_id,
        occurred_at=row.occurred_at,
    )
