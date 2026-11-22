"""notifications models: the in-app inbox and the email log (MASTER_PROMPT §3 item 14)."""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class Notification(TenantOwnedModel):
    """One in-app message for one user. Unique per (user, source event): handlers are idempotent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient_user_id = models.UUIDField()
    kind = models.CharField(max_length=64)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    source_event_id = models.BigIntegerField()
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "recipient_user_id", "source_event_id"], name="notification_once"
            )
        ]
        indexes = [
            models.Index(fields=["tenant", "recipient_user_id", "read_at"], name="notifications_inbox")
        ]


class EmailLog(TenantOwnedModel):
    """Every email the platform decided to send, and what happened (sent / suppressed / failed)."""

    id = models.BigAutoField(primary_key=True)
    to_address = models.EmailField()
    subject = models.CharField(max_length=200)
    kind = models.CharField(max_length=64)
    source_event_id = models.BigIntegerField()
    status = models.CharField(max_length=16)  # sent | suppressed | failed
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_log"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "to_address", "source_event_id"], name="email_once")
        ]
