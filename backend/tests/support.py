"""Test helpers: a committed fixture world built through the platform path, token minting with the
local issuer, and an API client that authenticates like a real client."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from django.db import connection
from django.test import Client

from corridor.core.platform import PlatformActor
from corridor.core.tenancy import clear_context
from corridor.identity.local_issuer import issue_access_token, local_sub
from corridor.identity.permissions import ClientKind
from corridor.identity.services import (
    platform_add_member,
    platform_create_tenant,
    platform_grant_admin,
    platform_set_tenant_status,
)

ACTOR = PlatformActor(user_id=None, reason="pytest fixture world (test database only)")


@dataclass(frozen=True)
class Member:
    key: str
    identifier: str  # email or phone used to sign in
    tenant: str
    role: str
    user_id: uuid.UUID
    membership_id: uuid.UUID
    client: ClientKind
    mfa: bool

    @property
    def sub(self) -> str:
        return local_sub(self.identifier)


@dataclass
class World:
    tenants: dict[str, uuid.UUID] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)
    platform_admin_identifier: str = "root@platform.test"
    platform_admin_id: uuid.UUID | None = None

    def m(self, key: str) -> Member:
        return self.members[key]


_CLIENT_FOR_ROLE = {"driver": ClientKind.DRIVER_MOBILE, "customer": ClientKind.WEB_PORTAL}
_MFA_ROLES = {"owner", "admin", "finance"}


def build_world() -> World:
    """Committed rows (TEST data, test database only; hard rule 7)."""
    w = World()

    def add(key: str, tenant: str, role: str, identifier: str, status: str = "active") -> None:
        is_phone = identifier.startswith("+")
        user_id, membership_id = platform_add_member(
            ACTOR,
            tenant_id=w.tenants[tenant],
            role=role,
            email=None if is_phone else identifier,
            phone=identifier if is_phone else None,
            display_name=f"TEST {key}",
            status=status,
        )
        w.members[key] = Member(
            key=key,
            identifier=identifier,
            tenant=tenant,
            role=role,
            user_id=user_id,
            membership_id=membership_id,
            client=_CLIENT_FOR_ROLE.get(role, ClientKind.WEB_OFFICE),
            mfa=role in _MFA_ROLES,
        )

    for slug in ("alpha", "bravo", "charlie"):
        out = platform_create_tenant(
            ACTOR,
            slug=slug,
            name=f"TEST {slug.title()} Logistics",
            owner_email=f"owner@{slug}.test",
            is_demo=True,
        )
        w.tenants[slug] = out.id
        assert out.owner_membership_id is not None
        # The owner membership starts "invited"; it becomes active on first sign-in.

    for role in ("admin", "ops_manager", "dispatcher", "fleet_manager", "finance", "customer"):
        add(f"alpha_{role}", "alpha", role, f"{role}@alpha.test")
    add("alpha_driver", "alpha", "driver", "+25377000001")
    add("alpha_suspended", "alpha", "dispatcher", "suspended@alpha.test", status="suspended")
    add("bravo_admin", "bravo", "admin", "admin@bravo.test")
    add("bravo_dispatcher", "bravo", "dispatcher", "dispatcher@bravo.test")
    add("bravo_driver", "bravo", "driver", "+25377000002")
    add("charlie_dispatcher", "charlie", "dispatcher", "dispatcher@charlie.test")
    # One person in two companies with different roles (tenant switching).
    add("multi_alpha", "alpha", "dispatcher", "multi@both.test")
    add("multi_bravo", "bravo", "ops_manager", "multi@both.test")

    platform_set_tenant_status(ACTOR, w.tenants["charlie"], suspended=True)
    w.platform_admin_id = platform_grant_admin(ACTOR, email=w.platform_admin_identifier)
    return w


def token_for(
    identifier: str,
    client: ClientKind = ClientKind.WEB_OFFICE,
    *,
    mfa: bool = False,
    session_ref: str | None = None,
    **kwargs: Any,
) -> str:
    return issue_access_token(local_sub(identifier), client, mfa=mfa, session_ref=session_ref, **kwargs)


def reset_db_context() -> None:
    """What a fresh request/connection would see: no tenant, no user (inside the test transaction,
    SET LOCAL values from a previous request would otherwise persist)."""
    if connection.in_atomic_block:
        with connection.cursor() as c:
            c.execute(
                "SELECT set_config('app.tenant_id', '', true), set_config('app.user_id', '', true),"
                " set_config('app.user_sub', '', true)"
            )
    clear_context()


class ApiClient:
    """Calls /api/v1 like a real client: bearer token, optional X-Tenant header."""

    def __init__(self, token: str | None, tenant: str | None = None) -> None:
        self.token = token
        self.tenant = tenant
        self._client = Client()

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        tenant: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        extra: dict[str, str] = {}
        if self.token:
            extra["HTTP_AUTHORIZATION"] = f"Bearer {self.token}"
        slug = tenant or self.tenant
        if slug:
            extra["HTTP_X_TENANT"] = slug
        for k, v in (headers or {}).items():
            extra["HTTP_" + k.upper().replace("-", "_")] = v
        kwargs: dict[str, Any] = {}
        if body is not None:
            kwargs = {"data": json.dumps(body), "content_type": "application/json"}
        response = getattr(self._client, method.lower())(f"/api/v1{path}", **kwargs, **extra)
        reset_db_context()
        try:
            data = response.json()
        except ValueError:
            data = response.content
        return response.status_code, data

    def get(self, path: str, **kw: Any) -> tuple[int, Any]:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.request("POST", path, body if body is not None else {}, **kw)

    def patch(self, path: str, body: Any = None, **kw: Any) -> tuple[int, Any]:
        return self.request("PATCH", path, body if body is not None else {}, **kw)


def client_for(member: Member, *, tenant: str | None = None, mfa: bool | None = None, **kw: Any) -> ApiClient:
    return ApiClient(
        token_for(member.identifier, member.client, mfa=member.mfa if mfa is None else mfa, **kw), tenant
    )


def owner_identifier(slug: str) -> str:
    return f"owner@{slug}.test"
