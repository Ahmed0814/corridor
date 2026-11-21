"""Request authentication and tenant context (docs/architecture/overview.md §4.1, D-006, D-041).

Runs inside the request transaction (Ninja authentication executes within ATOMIC_REQUESTS;
Django middleware does not, so it could not SET LOCAL). Steps:

1. Verify the Cognito access token (signature, iss, token_use, client_id, exp).
2. SET LOCAL app.user_sub, find the user by sub (RLS admits only that row).
3. SET LOCAL app.user_id, list the user's own memberships (self-read policy).
4. Pick the membership: the ``X-Tenant`` header (a slug, which must be one of the user's own
   tenants, else 404), else the tenant used last, else the oldest active membership. A client can
   choose among its memberships but can never name a tenant it does not belong to.
5. Refuse suspended tenants, suspended memberships, and a role used from the wrong app client.
6. SET LOCAL app.tenant_id. From here RLS and the scoped managers isolate the tenant.
7. Record a login (new Cognito session) and a tenant switch in the audit log; refresh the MFA
   status at each login; activate an invited membership on first use.
"""

from __future__ import annotations

import dataclasses
import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

import structlog
from django.db.models import Q
from django.http import HttpRequest
from django.utils import timezone
from ninja.security import HttpBearer

from corridor.audit import services as audit
from corridor.core.api import ApiError
from corridor.core.tenancy import apply_context
from corridor.identity.models import TenantMembership, User
from corridor.identity.permissions import PERMISSIONS, ROLES
from corridor.identity.providers import IdentityProviderError, get_provider
from corridor.identity.schemas import RequestContext
from corridor.identity.tokens import InvalidToken, VerifiedToken, get_verifier
from corridor.tenants import services as tenants

log = structlog.get_logger(__name__)

TENANT_HEADER = "X-Tenant"


def _not_found() -> ApiError:
    return ApiError(404, "not_found", "Not found.")


@dataclass(frozen=True, slots=True)
class _Resolved:
    ctx: RequestContext
    user: User


def _load_user(token: VerifiedToken) -> User:
    apply_context(user_sub=token.sub)
    user = User.objects.filter(cognito_sub=token.sub).first()
    if user is None or not user.is_active:
        # Valid Cognito user, but not (or no longer) a user of this platform.
        raise ApiError(403, "no_access", "This account has no access to Corridor.")
    apply_context(user_id=user.id, user_sub=token.sub)
    return user


def _refresh_session(user: User, token: VerifiedToken, memberships: list[TenantMembership]) -> bool:
    """On the first request of a new Cognito session: refresh MFA status. Returns True if this
    request is that first request (the caller records the login after choosing the tenant)."""
    if user.last_session_ref == token.session_ref:
        return False
    needs_mfa = user.is_platform_admin or any(ROLES[m.role_id].requires_mfa for m in memberships)
    mfa_at = user.mfa_verified_at
    if needs_mfa:
        try:
            mfa_at = timezone.now() if get_provider().mfa_enabled(token.sub, token.claims) else None
        except IdentityProviderError:
            # Fail closed and do not record the session, so the next request retries.
            log.warning("mfa_status_check_failed", exc_info=True)
            user.mfa_verified_at = None
            return False
    # Conditional update: of two concurrent first requests, only one records the login.
    updated = (
        User.objects.filter(id=user.id)
        .exclude(last_session_ref=token.session_ref)
        .update(last_session_ref=token.session_ref, mfa_verified_at=mfa_at, last_login=timezone.now())
    )
    user.mfa_verified_at = mfa_at
    user.last_session_ref = token.session_ref
    return updated == 1


def _choose(
    wanted: str | None, user: User, memberships: list[TenantMembership], require_tenant: bool
) -> TenantMembership | None:
    tenant_infos = tenants.tenants_by_ids(m.tenant_id for m in memberships)
    if wanted:
        for m in memberships:
            info = tenant_infos.get(m.tenant_id)
            if info is not None and info.slug == wanted:
                return m
        raise _not_found()  # not a member: indistinguishable from a tenant that does not exist
    usable = [m for m in memberships if m.status != TenantMembership.Status.SUSPENDED]
    last = next((m for m in usable if m.tenant_id == user.last_tenant_id), None)
    chosen = last or (usable[0] if usable else None)
    if chosen is None and require_tenant:
        if memberships:
            raise ApiError(403, "membership_suspended", "Your access to this company is suspended.")
        raise ApiError(403, "no_membership", "You are not a member of any company.")
    return chosen


def resolve(raw_token: str, *, tenant_slug: str | None, require_tenant: bool = True) -> _Resolved:
    """Must run inside a transaction (the request's, or one opened by the caller)."""
    try:
        token = get_verifier().verify(raw_token)
    except InvalidToken as exc:
        log.info("token_rejected", reason=str(exc))
        raise ApiError(401, "unauthenticated", "Authentication required.") from exc

    user = _load_user(token)
    memberships = list(
        TenantMembership._base_manager.filter(user_id=user.id)  # self-read policy; no tenant yet
        .filter(Q(status__in=["invited", "active", "suspended"]))
        .order_by("created_at")
    )
    new_session = _refresh_session(user, token, memberships)
    membership = _choose(tenant_slug, user, memberships, require_tenant)

    base = RequestContext(
        user_id=user.id,
        user_sub=token.sub,
        client_kind=token.client_kind,
        is_platform_admin=user.is_platform_admin,
        mfa_verified=user.mfa_verified_at is not None,
    )
    if membership is None:
        if new_session:
            audit.record(
                audit.LOGIN, tenant_id=None, actor_user_id=user.id, metadata={"client": token.client_kind}
            )
        return _Resolved(base, user)

    tenant_id: uuid.UUID = membership.tenant_id
    info = tenants.tenants_by_ids([tenant_id]).get(tenant_id)
    if info is None:
        raise _not_found()
    if info.status != tenants.SUSPENDED and membership.status == TenantMembership.Status.SUSPENDED:
        raise ApiError(403, "membership_suspended", "Your access to this company is suspended.")
    if info.status == tenants.SUSPENDED:
        raise ApiError(403, "tenant_suspended", "This company account is suspended.")
    role = ROLES[membership.role_id]
    if token.client_kind not in role.clients:
        raise ApiError(403, "wrong_client", "This role cannot sign in through this application.")

    apply_context(tenant_id=tenant_id, user_id=user.id, user_sub=token.sub)

    if membership.status == TenantMembership.Status.INVITED:
        TenantMembership.objects.filter(id=membership.id, status=TenantMembership.Status.INVITED).update(
            status=TenantMembership.Status.ACTIVE, activated_at=timezone.now()
        )
        audit.record(
            audit.MEMBERSHIP_ACTIVATED,
            tenant_id=tenant_id,
            actor_user_id=user.id,
            target_type="membership",
            target_id=membership.id,
        )
    if new_session:
        audit.record(
            audit.LOGIN, tenant_id=tenant_id, actor_user_id=user.id, metadata={"client": token.client_kind}
        )
    if user.last_tenant_id != tenant_id:
        if user.last_tenant_id is not None:
            audit.record(
                audit.TENANT_SWITCHED,
                tenant_id=tenant_id,
                actor_user_id=user.id,
                metadata={"from_tenant_id": str(user.last_tenant_id), "to_tenant_id": str(tenant_id)},
            )
        User.objects.filter(id=user.id).update(last_tenant_id=tenant_id)

    mfa_ok = (not role.requires_mfa) or user.mfa_verified_at is not None
    ctx = dataclasses.replace(
        base,
        tenant_id=tenant_id,
        tenant_slug=info.slug,
        membership_id=membership.id,
        role=role.code,
        scope=role.scope,
        customer_id=membership.customer_id,
        driver_id=membership.driver_id,
        permissions=role.permissions if mfa_ok else frozenset(),
        mfa_required=not mfa_ok,
    )
    structlog.contextvars.bind_contextvars(tenant_id=str(tenant_id), user_id=str(user.id))
    return _Resolved(ctx, user)


# --------------------------------------------------------------------------- Ninja integration


class TenantBearer(HttpBearer):
    """Bearer auth that also establishes the tenant context. ``request.auth`` is the context."""

    def __init__(self, *, require_tenant: bool = True) -> None:
        super().__init__()
        self.require_tenant = require_tenant

    def authenticate(self, request: HttpRequest, token: str) -> RequestContext:
        ctx = resolve(
            token, tenant_slug=request.headers.get(TENANT_HEADER), require_tenant=self.require_tenant
        ).ctx
        request.ctx = ctx  # type: ignore[attr-defined]
        return ctx


class PlatformBearer(HttpBearer):
    """Platform Super Admin: flag on the user, MFA verified, office client. No tenant context."""

    def authenticate(self, request: HttpRequest, token: str) -> RequestContext:
        ctx = resolve(token, tenant_slug=request.headers.get(TENANT_HEADER), require_tenant=False).ctx
        if not ctx.is_platform_admin:
            raise _not_found()  # do not advertise the platform API
        if not ctx.mfa_verified:
            raise ApiError(403, "mfa_required", "Multi-factor authentication is required.")
        if ctx.client_kind.value != "web-office":
            raise ApiError(403, "wrong_client", "Use the office application for platform administration.")
        request.ctx = ctx  # type: ignore[attr-defined]
        return ctx


def ctx_of(request: HttpRequest, *, need_tenant: bool = True) -> RequestContext:
    """The authenticated context of a request (set by TenantBearer/PlatformBearer)."""
    ctx = getattr(request, "auth", None)
    if not isinstance(ctx, RequestContext) or (need_tenant and ctx.tenant_id is None):
        raise ApiError(401, "unauthenticated", "Authentication required.")
    return ctx


tenant_auth = TenantBearer()
user_auth = TenantBearer(require_tenant=False)
platform_auth = PlatformBearer()

F = TypeVar("F", bound=Callable[..., Any])
PERMISSION_ATTR = "__corridor_permission__"
PUBLIC_ATTR = "__corridor_public__"
PLATFORM_ATTR = "__corridor_platform__"
AUTHENTICATED_ATTR = "__corridor_authenticated__"


def requires(permission: str) -> Callable[[F], F]:
    """Declare and enforce the permission an operation needs (security-model.md §3.1)."""
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")

    def decorator(fn: F) -> F:
        @wraps(fn)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            ctx = getattr(request, "auth", None)
            if not isinstance(ctx, RequestContext) or ctx.tenant_id is None:
                raise ApiError(401, "unauthenticated", "Authentication required.")
            if not ctx.has(permission):
                if ctx.mfa_required and ctx.role and permission in ROLES[ctx.role].permissions:
                    raise ApiError(
                        403, "mfa_required", "Multi-factor authentication is required for this role."
                    )
                raise ApiError(403, "forbidden", "You do not have permission for this action.")
            return fn(request, *args, **kwargs)

        # Ninja resolves string annotations (PEP 563) in the wrapper's module globals, which are
        # this module's. Hand it the evaluated signature of the real view instead.
        wrapper.__signature__ = inspect.signature(fn, eval_str=True)  # type: ignore[attr-defined]
        setattr(wrapper, PERMISSION_ATTR, permission)
        return wrapper  # type: ignore[return-value]

    return decorator


def authenticated_only[F: Callable[..., Any]](fn: F) -> F:
    """Any signed-in user (e.g. /me). Data access inside must still be scoped to the user."""
    setattr(fn, AUTHENTICATED_ATTR, True)
    return fn


def platform_only[F: Callable[..., Any]](fn: F) -> F:
    setattr(fn, PLATFORM_ATTR, True)
    return fn


def public[F: Callable[..., Any]](fn: F) -> F:
    """No authentication by design (health, metadata, public tracking links)."""
    setattr(fn, PUBLIC_ATTR, True)
    return fn
