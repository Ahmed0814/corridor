"""Identity: the platform user.

Defined in Phase 1 because AUTH_USER_MODEL cannot be changed cheaply after the first
migration. Users are global (not tenant-owned); tenant access comes only from
tenant_memberships (Phase 2). Authentication is Amazon Cognito; no local passwords are used
for tenant users (set_unusable_password on creation).
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


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
