"""drivers models. A driver is an assigned operator (MASTER_PROMPT §3 modeling rules).

Personal data is protected: the license number is stored encrypted (core.crypto, D-019) with a
keyed hash for uniqueness, and is only returned to callers with ``drivers.pii``.
"""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class Driver(TenantOwnedModel):
    class Employment(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"
        TERMINATED = "terminated"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    full_name = models.CharField(max_length=200)
    phone_e164 = models.CharField(max_length=16, blank=True)
    license_number_enc = models.TextField(blank=True)
    license_number_hash = models.CharField(max_length=64, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    employment_status = models.CharField(max_length=16, choices=Employment.choices, default=Employment.ACTIVE)
    tracking_consent = models.BooleanField(default=False)
    tracking_consent_at = models.DateTimeField(null=True, blank=True)
    # The driver's sign-in membership (identity module). A plain id, not a cross-module FK.
    membership_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "drivers"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "license_number_hash"],
                condition=~models.Q(license_number_hash=""),
                name="drivers_license_unique",
            ),
            models.UniqueConstraint(
                fields=["tenant", "membership_id"],
                condition=models.Q(membership_id__isnull=False),
                name="drivers_membership_unique",
            ),
        ]
