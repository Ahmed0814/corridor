"""audit models. Private to this module (DECISIONS D-005).

Append-only (D-018): the app role has SELECT and INSERT only. RLS: the app role reads rows of the
current tenant, and may insert rows for the current tenant or tenant-less rows about itself.
"""

from __future__ import annotations

from typing import Any

from django.db import models


def empty_metadata() -> dict[str, Any]:
    return {}


class AuditLog(models.Model):
    class ActorKind(models.TextChoices):
        USER = "user", "User"
        SYSTEM = "system", "System"
        INTEGRATION = "integration", "Integration"
        PLATFORM_ADMIN = "platform_admin", "Platform admin"

    id = models.BigAutoField(primary_key=True)
    # Nullable: platform-level actions have no tenant. Not a TenantOwnedModel for that reason.
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    actor_user_id = models.UUIDField(null=True, blank=True)
    actor_kind = models.CharField(max_length=16, choices=ActorKind.choices)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=empty_metadata, blank=True)
    request_id = models.CharField(max_length=128, blank=True, default="")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_logs"
        indexes = [
            models.Index(fields=["tenant", "-occurred_at"], name="audit_logs_tenant_time_idx"),
            models.Index(fields=["action", "-occurred_at"], name="audit_logs_action_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action}@{self.occurred_at}"
