"""identity Ninja routers: the current user, company members, and the platform admin API."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.platform import PlatformActor
from corridor.identity import services
from corridor.identity.schemas import (
    InviteIn,
    MemberOut,
    MeOut,
    PlatformTenantOut,
    RequestContext,
    RoleChangeIn,
)
from corridor.tenants.schemas import TenantCreateIn

router = Router(tags=["identity"], auth=services.tenant_auth)
me_router = Router(tags=["identity"], auth=services.user_auth)
platform_router = Router(tags=["platform"], auth=services.platform_auth)


def _ctx(request: HttpRequest) -> RequestContext:
    return services.ctx_of(request, need_tenant=False)


@me_router.get("/me", response=MeOut, summary="The signed-in user, active company and permissions")
@services.authenticated_only
def get_me(request: HttpRequest) -> MeOut:
    return services.me(_ctx(request))


@router.get("/memberships", response=list[MemberOut], summary="Members of the active company")
@services.requires("users.manage")
def list_memberships(request: HttpRequest) -> list[MemberOut]:
    return services.list_members(_ctx(request))


@router.post("/memberships", response={201: MemberOut}, summary="Invite a member")
@services.requires("users.manage")
def invite(request: HttpRequest, payload: InviteIn) -> Status[MemberOut]:
    return Status(201, services.invite_member(_ctx(request), payload))


@router.post("/memberships/{membership_id}/role", response=MemberOut, summary="Change a member's role")
@services.requires("roles.assign")
def change_role(request: HttpRequest, membership_id: uuid.UUID, payload: RoleChangeIn) -> MemberOut:
    return services.change_role(_ctx(request), membership_id, payload.role)


@router.post("/memberships/{membership_id}/suspend", response=MemberOut, summary="Suspend a member")
@services.requires("users.manage")
def suspend(request: HttpRequest, membership_id: uuid.UUID) -> MemberOut:
    return services.set_member_status(_ctx(request), membership_id, suspended=True)


@router.post("/memberships/{membership_id}/reactivate", response=MemberOut, summary="Reactivate a member")
@services.requires("users.manage")
def reactivate(request: HttpRequest, membership_id: uuid.UUID) -> MemberOut:
    return services.set_member_status(_ctx(request), membership_id, suspended=False)


# --------------------------------------------------------------------------- platform admin


def _actor(request: HttpRequest, reason: str) -> PlatformActor:
    return PlatformActor(user_id=_ctx(request).user_id, reason=reason)


@platform_router.get("/platform/tenants", response=list[PlatformTenantOut], summary="All companies")
@services.platform_only
def platform_tenants(request: HttpRequest) -> list[PlatformTenantOut]:
    return services.platform_list_tenants(_actor(request, "list tenants"))


@platform_router.post("/platform/tenants", response={201: PlatformTenantOut}, summary="Create a company")
@services.platform_only
def platform_create_tenant(request: HttpRequest, payload: TenantCreateIn) -> Status[PlatformTenantOut]:
    return Status(
        201,
        services.platform_create_tenant(
            _actor(request, "create tenant"),
            slug=payload.slug,
            name=payload.name,
            owner_email=payload.owner_email,
            owner_display_name=payload.owner_display_name,
            is_demo=payload.is_demo,
        ),
    )


@platform_router.post("/platform/tenants/{tenant_id}/suspend", response=PlatformTenantOut, summary="Suspend")
@services.platform_only
def platform_suspend(request: HttpRequest, tenant_id: uuid.UUID) -> PlatformTenantOut:
    return services.platform_set_tenant_status(_actor(request, "suspend tenant"), tenant_id, suspended=True)


@platform_router.post(
    "/platform/tenants/{tenant_id}/activate", response=PlatformTenantOut, summary="Activate"
)
@services.platform_only
def platform_activate(request: HttpRequest, tenant_id: uuid.UUID) -> PlatformTenantOut:
    return services.platform_set_tenant_status(_actor(request, "activate tenant"), tenant_id, suspended=False)
