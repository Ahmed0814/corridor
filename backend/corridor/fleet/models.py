"""fleet models. A vehicle is a transport asset (MASTER_PROMPT §3 modeling rules).

"Assigned" is not stored: it is derived from an active trip assignment (trips module), so it can
never drift from the assignment table (docs/architecture/state-machines.md, Vehicle).
"""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class AssetStatus(models.TextChoices):
    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    RETIRED = "retired"  # terminal


class Vehicle(TenantOwnedModel):
    class Kind(models.TextChoices):
        TRACTOR = "tractor"
        RIGID = "rigid"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plate = models.CharField(max_length=20)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.TRACTOR)
    make = models.CharField(max_length=60, blank=True)
    model = models.CharField(max_length=60, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=AssetStatus.choices, default=AssetStatus.AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "vehicles"
        constraints = [models.UniqueConstraint(fields=["tenant", "plate"], name="vehicles_plate_unique")]


class Trailer(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    plate = models.CharField(max_length=20)
    kind = models.CharField(max_length=32, blank=True)  # flatbed, skeletal, ...
    status = models.CharField(max_length=16, choices=AssetStatus.choices, default=AssetStatus.AVAILABLE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trailers"
        constraints = [models.UniqueConstraint(fields=["tenant", "plate"], name="trailers_plate_unique")]
