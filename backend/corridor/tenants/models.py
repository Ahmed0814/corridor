"""tenants models. Private to this module (DECISIONS D-005)."""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models


def default_settings() -> dict[str, Any]:
    return {}


class Tenant(models.Model):
    """A company using the platform.

    Not tenant-owned itself, but protected by RLS: the app role sees only the tenant of the
    current context and the tenants the current user belongs to. Status changes are
    platform-only (the app role has a column-level UPDATE grant on name/settings only).
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=63, unique=True)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    is_demo = models.BooleanField(default=False)
    settings = models.JSONField(default=default_settings, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "suspended"]), name="tenants_status_valid"
            ),
        ]

    def __str__(self) -> str:
        return self.slug
