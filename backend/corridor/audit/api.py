"""audit Ninja router: the active company's audit log (read-only)."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Query, Router, Schema
from pydantic import Field

from corridor.audit import services
from corridor.audit.schemas import AuditEntry
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["audit"], auth=tenant_auth)


class AuditQuery(Schema):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    action: str | None = Field(default=None, max_length=64)


@router.get("/audit-logs", response=list[AuditEntry], summary="Audit log of the active company")
@requires("audit.read")
def list_audit_logs(request: HttpRequest, filters: Query[AuditQuery]) -> list[AuditEntry]:
    ctx = ctx_of(request)
    if ctx.tenant_id is None:  # narrowed by ctx_of; keeps the type checker informed
        raise RuntimeError("tenant context missing")
    return services.list_entries(
        tenant_id=ctx.tenant_id, limit=filters.limit, offset=filters.offset, action=filters.action
    )
