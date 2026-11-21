"""core models. Private to this module (DECISIONS D-005)."""

from __future__ import annotations

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class IdempotencyKey(TenantOwnedModel):
    """One row per (tenant, user, Idempotency-Key) for state-changing requests (D-015).

    ``response_status = 0`` marks a request still in progress (the row is inserted first, so a
    concurrent duplicate waits on the unique index and then replays the stored result).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.UUIDField()
    key = models.CharField(max_length=128)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(default=0)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "idempotency_keys"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user_id", "key"], name="idempotency_key_unique"),
        ]
