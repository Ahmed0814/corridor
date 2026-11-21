"""identity Pydantic/Ninja schemas (public DTOs) and the RequestContext."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ninja import Field, Schema
from pydantic import ConfigDict, model_validator

from corridor.identity.permissions import ClientKind, Scope


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Who is acting, for which tenant, with which permissions. Built only by the server from a
    verified token and the user's membership (hard rule 2); never from client-supplied ids."""

    user_id: uuid.UUID
    user_sub: str
    client_kind: ClientKind
    is_platform_admin: bool
    mfa_verified: bool
    tenant_id: uuid.UUID | None = None
    tenant_slug: str | None = None
    membership_id: uuid.UUID | None = None
    role: str | None = None
    scope: Scope | None = None
    customer_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    mfa_required: bool = False  # the role needs MFA that is not verified: permissions withheld

    def has(self, permission: str) -> bool:
        return self.tenant_id is not None and permission in self.permissions


RoleCode = Literal[
    "owner", "admin", "ops_manager", "dispatcher", "fleet_manager", "finance", "driver", "customer"
]


class MembershipSummary(Schema):
    tenant_id: uuid.UUID
    tenant_slug: str
    tenant_name: str
    tenant_status: str
    role: str
    status: str


class MeOut(Schema):
    user_id: uuid.UUID
    display_name: str
    email: str | None
    is_platform_admin: bool
    mfa_verified: bool
    client: str
    active_tenant: MembershipSummary | None
    permissions: list[str]
    mfa_required: bool
    memberships: list[MembershipSummary]


class MemberOut(Schema):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    email: str | None
    phone_masked: str | None
    role: str
    status: str
    created_at: datetime
    activated_at: datetime | None


class InviteIn(Schema):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone_e164: str | None = Field(default=None, pattern=r"^\+[1-9]\d{6,14}$")
    display_name: str = Field(default="", max_length=200)
    role: RoleCode

    @model_validator(mode="after")
    def _one_identifier(self) -> InviteIn:
        if not self.email and not self.phone_e164:
            raise ValueError("email or phone_e164 is required")
        if self.role == "driver" and not self.phone_e164:
            raise ValueError("drivers sign in with a phone number")
        if self.role != "driver" and not self.email:
            raise ValueError("office and customer users sign in with an email address")
        return self


class RoleChangeIn(Schema):
    model_config = ConfigDict(extra="forbid")

    role: RoleCode


class PlatformTenantOut(Schema):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    is_demo: bool
    owner_membership_id: uuid.UUID | None = None
