"""tenants Ninja router: the active company's profile."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from corridor.audit import services as audit
from corridor.core.api import ApiError
from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.tenants import services
from corridor.tenants.schemas import TenantProfile, TenantUpdateIn

router = Router(tags=["tenant"], auth=tenant_auth)


@router.get("/tenant", response=TenantProfile, summary="The active company")
@requires("tenant.read")
def get_tenant(request: HttpRequest) -> TenantProfile:
    return services.current_profile()


@router.patch("/tenant", response=TenantProfile, summary="Update the active company's profile")
@requires("tenant.settings")
def update_tenant(request: HttpRequest, payload: TenantUpdateIn) -> TenantProfile:
    ctx = ctx_of(request)
    try:
        profile, changed = services.update_current(name=payload.name, settings=payload.settings)
    except services.InvalidTenantSettings as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc
    if changed:
        audit.record(
            audit.TENANT_SETTINGS_CHANGED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            target_type="tenant",
            target_id=str(ctx.tenant_id),
            metadata={"fields": changed},
        )
    return profile
