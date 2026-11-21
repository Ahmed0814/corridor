"""events models: the transactional outbox (MASTER_PROMPT §5, DECISIONS D-014, D-051)."""

from __future__ import annotations

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class OutboxEvent(TenantOwnedModel):
    """A business event written in the same transaction as the change that caused it.

    The app role may only INSERT (and SELECT its own tenant's rows). The relay role reads
    unpublished rows of every tenant and marks them published; nothing else.
    """

    id = models.BigAutoField(primary_key=True)
    type = models.CharField(max_length=64)
    aggregate_type = models.CharField(max_length=32)
    aggregate_id = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    request_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "outbox_events"
        indexes = [
            models.Index(
                fields=["id"], name="outbox_unpublished_idx", condition=models.Q(published_at__isnull=True)
            ),
        ]
