"""identity public interface. Other modules may import only this file and schemas.py (D-005).

Exports the authentication classes and permission decorators every module's api.py uses, the
RequestContext type, and the membership services.
"""

from __future__ import annotations

import uuid

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from corridor.audit import services as audit
from corridor.core.api import ApiError
from corridor.core.platform import PLATFORM_DB, PlatformActor, platform_session
from corridor.core.tenancy import current_context, tenant_context
from corridor.identity.auth import (
    AUTHENTICATED_ATTR,
    PERMISSION_ATTR,
    PLATFORM_ATTR,
    PUBLIC_ATTR,
    TENANT_HEADER,
    authenticated_only,
    ctx_of,
    platform_auth,
    platform_only,
    public,
    requires,
    resolve,
    tenant_auth,
    user_auth,
)
from corridor.identity.models import TenantMembership, User
from corridor.identity.permissions import ADMIN_ASSIGNABLE, ROLES, ClientKind, Scope
from corridor.identity.providers import IdentityProviderError, get_provider
from corridor.identity.schemas import (
    InviteIn,
    MemberOut,
    MembershipSummary,
    MeOut,
    PlatformTenantOut,
    RequestContext,
)
from corridor.tenants import services as tenants
from corridor.tenants.schemas import TenantInfo

__all__ = [
    "AUTHENTICATED_ATTR",
    "PERMISSION_ATTR",
    "PLATFORM_ATTR",
    "PUBLIC_ATTR",
    "TENANT_HEADER",
    "ClientKind",
    "RequestContext",
    "Scope",
    "authenticated_only",
    "change_role",
    "ctx_of",
    "invite_member",
    "list_members",
    "me",
    "platform_add_member",
    "platform_auth",
    "platform_create_tenant",
    "platform_grant_admin",
    "platform_list_tenants",
    "platform_only",
    "platform_set_tenant_status",
    "public",
    "requires",
    "resolve_token",
    "set_member_status",
    "tenant_auth",
    "user_auth",
]

Status = TenantMembership.Status


def resolve_token(raw_token: str, *, tenant_slug: str | None) -> RequestContext:
    """Authenticate outside HTTP (WebSocket). Caller must hold an open transaction; raises
    corridor.core.api.ApiError like the HTTP path."""
    return resolve(raw_token, tenant_slug=tenant_slug).ctx


def _mask_phone(phone: str | None) -> str | None:
    return f"{phone[:4]}•••{phone[-2:]}" if phone else None


def _summary(m: TenantMembership, info: TenantInfo) -> MembershipSummary:
    return MembershipSummary(
        tenant_id=info.id,
        tenant_slug=info.slug,
        tenant_name=info.name,
        tenant_status=info.status,
        role=m.role_id,
        status=m.status,
    )


def me(ctx: RequestContext) -> MeOut:
    user = User.objects.get(id=ctx.user_id)
    memberships = list(TenantMembership._base_manager.filter(user_id=ctx.user_id).order_by("created_at"))
    infos = tenants.tenants_by_ids(m.tenant_id for m in memberships)
    summaries = [_summary(m, infos[m.tenant_id]) for m in memberships if m.tenant_id in infos]
    active = next((s for s in summaries if s.tenant_id == ctx.tenant_id), None)
    return MeOut(
        user_id=user.id,
        display_name=user.display_name,
        email=user.email,
        is_platform_admin=user.is_platform_admin,
        mfa_verified=ctx.mfa_verified,
        client=ctx.client_kind.value,
        active_tenant=active,
        permissions=sorted(ctx.permissions),
        mfa_required=ctx.mfa_required,
        memberships=summaries,
    )


def _member_out(m: TenantMembership, user: User) -> MemberOut:
    return MemberOut(
        id=m.id,
        user_id=user.id,
        display_name=user.display_name,
        email=user.email,
        phone_masked=_mask_phone(user.phone_e164),
        role=m.role_id,
        status=m.status,
        created_at=m.created_at,
        activated_at=m.activated_at,
    )


def list_members(ctx: RequestContext) -> list[MemberOut]:
    memberships = list(TenantMembership.objects.order_by("created_at"))
    users = {u.id: u for u in User.objects.filter(id__in=[m.user_id for m in memberships])}
    return [_member_out(m, users[m.user_id]) for m in memberships if m.user_id in users]


def _get_membership_for_update(membership_id: uuid.UUID) -> TenantMembership:
    m: TenantMembership | None = TenantMembership.objects.select_for_update().filter(id=membership_id).first()
    if m is None:
        raise ApiError(404, "not_found", "Not found.")  # also for another tenant's membership
    return m


def _check_owner_rules(ctx: RequestContext, target: TenantMembership, new_role: str | None) -> None:
    if target.user_id == ctx.user_id:
        raise ApiError(409, "conflict", "You cannot change your own membership.")
    touches_owner = target.role_id == "owner" or new_role == "owner"
    if touches_owner and ctx.role != "owner":
        raise ApiError(403, "forbidden", "Only a company owner can manage owners.")


def _ensure_another_owner(target: TenantMembership) -> None:
    others = (
        TenantMembership.objects.select_for_update()
        .filter(role_id="owner", status=Status.ACTIVE)
        .exclude(id=target.id)
        .count()
    )
    if others == 0:
        raise ApiError(409, "conflict", "A company must keep at least one active owner.")


def invite_member(ctx: RequestContext, data: InviteIn) -> MemberOut:
    if data.role == "owner" and ctx.role != "owner":
        raise ApiError(403, "forbidden", "Only a company owner can invite an owner.")
    if data.role not in ADMIN_ASSIGNABLE and data.role != "owner":
        raise ApiError(422, "validation_error", "Unknown role.")
    email = data.email.strip().lower() if data.email else None
    try:
        sub = get_provider().ensure_user(
            email=email, phone_e164=data.phone_e164, display_name=data.display_name
        )
    except IdentityProviderError as exc:
        raise ApiError(
            502, "identity_provider_error", "The identity provider rejected the invitation."
        ) from exc
    with connection.cursor() as cursor:
        try:
            with transaction.atomic():
                cursor.execute(
                    "SELECT identity_upsert_user(%s, %s, %s, %s)",
                    [sub, email, data.phone_e164, data.display_name],
                )
        except IntegrityError as exc:
            raise ApiError(409, "conflict", "This email or phone is linked to a different sign-in.") from exc
        row = cursor.fetchone()
    if row is None:  # the function always returns an id; defensive
        raise ApiError(500, "internal_error", "Could not create the user.")
    user_id = row[0]
    if TenantMembership.objects.filter(user_id=user_id).exists():
        raise ApiError(409, "conflict", "This person is already a member of the company.")
    m = TenantMembership.for_context(
        user_id=user_id, role_id=data.role, status=Status.INVITED, invited_by_id=ctx.user_id
    )
    try:
        with transaction.atomic():
            m.save()
    except IntegrityError as exc:  # concurrent invitation of the same person
        raise ApiError(409, "conflict", "This person is already a member of the company.") from exc
    audit.record(
        audit.MEMBERSHIP_INVITED,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        target_type="membership",
        target_id=m.id,
        metadata={"role": data.role},
    )
    return _member_out(m, User.objects.get(id=user_id))


def change_role(ctx: RequestContext, membership_id: uuid.UUID, new_role: str) -> MemberOut:
    if new_role not in ROLES:
        raise ApiError(422, "validation_error", "Unknown role.")
    target = _get_membership_for_update(membership_id)
    _check_owner_rules(ctx, target, new_role)
    old_role = target.role_id
    if old_role != new_role:
        if old_role == "owner":
            _ensure_another_owner(target)
        target.role_id = new_role
        target.save(update_fields=["role", "updated_at"])
        audit.record(
            audit.ROLE_CHANGED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            target_type="membership",
            target_id=target.id,
            metadata={"from": old_role, "to": new_role, "user_id": str(target.user_id)},
        )
    return _member_out(target, User.objects.get(id=target.user_id))


def set_member_status(ctx: RequestContext, membership_id: uuid.UUID, *, suspended: bool) -> MemberOut:
    target = _get_membership_for_update(membership_id)
    _check_owner_rules(ctx, target, None)
    if suspended and target.status != Status.SUSPENDED:
        if target.role_id == "owner":
            _ensure_another_owner(target)
        target.status = Status.SUSPENDED
        target.save(update_fields=["status", "updated_at"])
        audit.record(
            audit.MEMBERSHIP_SUSPENDED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            target_type="membership",
            target_id=target.id,
        )
    elif not suspended and target.status == Status.SUSPENDED:
        target.status = Status.ACTIVE if target.activated_at else Status.INVITED
        target.save(update_fields=["status", "updated_at"])
        audit.record(
            audit.MEMBERSHIP_REACTIVATED,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            target_type="membership",
            target_id=target.id,
        )
    return _member_out(target, User.objects.get(id=target.user_id))


# --------------------------------------------------------------------------- platform path
# Runs as corridor_platform inside platform_session(); every action is audited with
# actor_kind=platform_admin (or system for operator CLI commands).


def _actor_kind(actor: PlatformActor) -> str:
    return audit.ActorKind.PLATFORM_ADMIN if actor.user_id else audit.ActorKind.SYSTEM


def _platform_upsert_user(*, email: str | None, phone: str | None, display_name: str) -> User:
    sub = get_provider().ensure_user(email=email, phone_e164=phone, display_name=display_name)
    users = User.objects.using(PLATFORM_DB)
    user = users.filter(cognito_sub=sub).first()
    if user is None and email:
        user = users.filter(email__iexact=email).first()
    if user is None and phone:
        user = users.filter(phone_e164=phone).first()
    if user is None:
        user = User(cognito_sub=sub, email=email, phone_e164=phone, display_name=display_name)
        user.set_unusable_password()
        user.save(using=PLATFORM_DB)
    elif user.cognito_sub is None:
        user.cognito_sub = sub
        user.save(using=PLATFORM_DB, update_fields=["cognito_sub", "updated_at"])
    elif user.cognito_sub != sub:
        raise ApiError(409, "conflict", "This email or phone is linked to a different sign-in.")
    return user


def platform_create_tenant(
    actor: PlatformActor,
    *,
    slug: str,
    name: str,
    owner_email: str,
    owner_display_name: str = "",
    is_demo: bool = False,
) -> PlatformTenantOut:
    with platform_session(actor):
        if tenants.platform_slug_exists(slug):
            raise ApiError(409, "conflict", "A company with this identifier already exists.")
        info = tenants.platform_create(slug=slug, name=name, is_demo=is_demo)
        owner = _platform_upsert_user(
            email=owner_email.strip().lower(), phone=None, display_name=owner_display_name
        )
        with tenant_context(info.id, using=PLATFORM_DB):
            m = TenantMembership.for_context(user_id=owner.id, role_id="owner", status=Status.INVITED)
            m.save(using=PLATFORM_DB)
        audit.record(
            audit.TENANT_CREATED,
            tenant_id=info.id,
            actor_user_id=actor.user_id,
            actor_kind=_actor_kind(actor),
            target_type="tenant",
            target_id=info.id,
            metadata={
                "slug": slug,
                "reason": actor.reason,
                "owner_user_id": str(owner.id),
                "is_demo": is_demo,
            },
            using=PLATFORM_DB,
        )
        return PlatformTenantOut(**info.model_dump(), owner_membership_id=m.id)


def platform_add_member(
    actor: PlatformActor,
    *,
    tenant_id: uuid.UUID,
    role: str,
    email: str | None = None,
    phone: str | None = None,
    display_name: str = "",
    status: str = Status.ACTIVE,
    customer_id: uuid.UUID | None = None,
    driver_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Operator/test tooling: add a member directly. Returns (user_id, membership_id)."""
    with platform_session(actor):
        user = _platform_upsert_user(email=email, phone=phone, display_name=display_name)
        with tenant_context(tenant_id, using=PLATFORM_DB):
            m = TenantMembership.for_context(
                user_id=user.id,
                role_id=role,
                status=status,
                customer_id=customer_id,
                driver_id=driver_id,
                activated_at=timezone.now() if status == Status.ACTIVE else None,
            )
            m.save(using=PLATFORM_DB)
        audit.record(
            audit.MEMBERSHIP_INVITED,
            tenant_id=tenant_id,
            actor_user_id=actor.user_id,
            actor_kind=_actor_kind(actor),
            target_type="membership",
            target_id=m.id,
            metadata={"role": role, "reason": actor.reason},
            using=PLATFORM_DB,
        )
        return user.id, m.id


def platform_grant_admin(actor: PlatformActor, *, email: str, display_name: str = "") -> uuid.UUID:
    with platform_session(actor):
        user = _platform_upsert_user(email=email.strip().lower(), phone=None, display_name=display_name)
        if not user.is_platform_admin:
            user.is_platform_admin = True
            user.save(using=PLATFORM_DB, update_fields=["is_platform_admin", "updated_at"])
        audit.record(
            "platform.admin_granted",
            tenant_id=None,
            actor_user_id=actor.user_id,
            actor_kind=_actor_kind(actor),
            target_type="user",
            target_id=user.id,
            metadata={"reason": actor.reason},
            using=PLATFORM_DB,
        )
        return user.id


def platform_list_tenants(actor: PlatformActor) -> list[PlatformTenantOut]:
    with platform_session(actor):
        rows = tenants.platform_list()
        audit.record(
            audit.PLATFORM_READ,
            tenant_id=None,
            actor_user_id=actor.user_id,
            actor_kind=_actor_kind(actor),
            target_type="tenant",
            metadata={"resource": "tenants", "count": len(rows), "reason": actor.reason},
            using=PLATFORM_DB,
        )
        return [PlatformTenantOut(**t.model_dump()) for t in rows]


def platform_set_tenant_status(
    actor: PlatformActor, tenant_id: uuid.UUID, *, suspended: bool
) -> PlatformTenantOut:
    with platform_session(actor):
        try:
            info, previous = tenants.platform_set_status(
                tenant_id, tenants.SUSPENDED if suspended else tenants.ACTIVE
            )
        except tenants.TenantNotFound as exc:
            raise ApiError(404, "not_found", "Not found.") from exc
        if previous != info.status:
            audit.record(
                audit.TENANT_SUSPENDED if suspended else audit.TENANT_ACTIVATED,
                tenant_id=tenant_id,
                actor_user_id=actor.user_id,
                actor_kind=_actor_kind(actor),
                target_type="tenant",
                target_id=tenant_id,
                metadata={"reason": actor.reason},
                using=PLATFORM_DB,
            )
        return PlatformTenantOut(**info.model_dump())


# --------------------------------------------------------------------------- scope links (Phase 3)


def _attach_profile(membership_id: uuid.UUID, *, role: str, field: str, profile_id: uuid.UUID) -> None:
    """Link a driver/customer profile to a membership of the current tenant (RLS-scoped lookup)."""
    m: TenantMembership | None = TenantMembership.objects.select_for_update().filter(id=membership_id).first()
    if m is None:
        raise ApiError(404, "not_found", "Not found.")
    if m.role_id != role:
        raise ApiError(409, "wrong_role", f"Only a {role} membership can be linked to this profile.")
    current = getattr(m, field)
    if current is not None and current != profile_id:
        raise ApiError(409, "already_linked", "That account is linked to another profile.")
    setattr(m, field, profile_id)
    m.save(update_fields=[field, "updated_at"])
    audit.record(
        audit.MEMBERSHIP_PROFILE_LINKED,
        tenant_id=m.tenant_id,
        actor_user_id=current_context().user_id,
        target_type="membership",
        target_id=str(m.id),
        metadata={field: str(profile_id)},
    )


def attach_driver_profile(membership_id: uuid.UUID, driver_id: uuid.UUID) -> None:
    _attach_profile(membership_id, role="driver", field="driver_id", profile_id=driver_id)


def attach_customer_profile(membership_id: uuid.UUID, customer_id: uuid.UUID) -> None:
    _attach_profile(membership_id, role="customer", field="customer_id", profile_id=customer_id)
