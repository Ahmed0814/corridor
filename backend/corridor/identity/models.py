"""Identity: the platform user.

Users are global (not tenant-owned); tenant access comes only from tenant_memberships.
Authentication is Amazon Cognito; no local passwords are used for tenant users
(set_unusable_password on creation). Roles and permissions are platform-defined
(identity/permissions.py, D-008); the tables below mirror that file.

RLS (migration 0002): the app role sees a user row only if it is the current user or a member
of the current tenant, and may update only its own row. Users are created through
identity_upsert_user() (SECURITY DEFINER) or the platform path, never by a plain INSERT.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class UserManager(BaseUserManager["User"]):
    def create_user(self, email: str | None = None, **extra: Any) -> User:
        user = self.model(email=self.normalize_email(email) if email else None, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        """Internal platform tooling only (Django admin). Requires MFA via Cognito in deployed envs."""
        user = self.model(email=self.normalize_email(email), is_staff=True, is_superuser=True, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cognito_sub = models.CharField(max_length=64, unique=True, null=True, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone_e164 = models.CharField(max_length=16, unique=True, null=True, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    is_platform_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)  # Django admin access (internal tools)
    is_active = models.BooleanField(default=True)
    mfa_verified_at = models.DateTimeField(null=True, blank=True)
    # Cognito session marker (origin_jti, else auth_time) of the last recorded login (audit).
    last_session_ref = models.CharField(max_length=128, blank=True, default="")
    # Tenant used by the previous request; a different one is recorded as a tenant switch.
    last_tenant_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(email__isnull=False) | models.Q(phone_e164__isnull=False),
                name="users_email_or_phone_required",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name or self.email or self.phone_e164 or str(self.id)


class Role(models.Model):
    code = models.CharField(primary_key=True, max_length=32)
    name = models.CharField(max_length=100)
    requires_mfa = models.BooleanField(default=False)
    scope = models.CharField(max_length=16)

    class Meta:
        db_table = "roles"

    def __str__(self) -> str:
        return self.code


class Permission(models.Model):
    code = models.CharField(primary_key=True, max_length=64)
    description = models.CharField(max_length=200)

    class Meta:
        db_table = "permissions"

    def __str__(self) -> str:
        return self.code


class RolePermission(models.Model):
    id = models.BigAutoField(primary_key=True)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, db_column="role_code", related_name="+")
    permission = models.ForeignKey(
        Permission, on_delete=models.CASCADE, db_column="permission_code", related_name="+"
    )

    class Meta:
        db_table = "role_permissions"
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="role_permissions_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.permission_id}"


class TenantMembership(TenantOwnedModel):
    """A user's role in one tenant. The only source of tenant access (hard rule 2)."""

    class Status(models.TextChoices):
        INVITED = "invited", "Invited"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, db_column="role_code", related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.INVITED)
    # Scope links for the Customer and Driver roles. Foreign keys to customers/drivers are
    # added in Phase 3 together with those tables.
    customer_id = models.UUIDField(null=True, blank=True)
    driver_id = models.UUIDField(null=True, blank=True)
    invited_by_id = models.UUIDField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant_memberships"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="tenant_memberships_one_per_user"),
            models.CheckConstraint(
                condition=models.Q(status__in=["invited", "active", "suspended"]),
                name="tenant_memberships_status_valid",
            ),
        ]
        indexes = [models.Index(fields=["user", "status"], name="tenant_memberships_user_idx")]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.tenant_id}:{self.role_id}"
