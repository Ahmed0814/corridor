"""containers models. A container is a physical asset (MASTER_PROMPT §3 modeling rules)."""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class Container(TenantOwnedModel):
    class Condition(models.TextChoices):
        GOOD = "good"
        DAMAGED = "damaged"
        NEEDS_REPAIR = "needs_repair"

    class Availability(models.TextChoices):
        AVAILABLE = "available"
        IN_USE = "in_use"  # on an active shipment (set by shipments services)
        MAINTENANCE = "maintenance"
        RETIRED = "retired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=11)  # ISO 6346, check digit validated in services
    iso_type = models.CharField(max_length=4, blank=True)  # e.g. 22G1, 45G1
    size_ft = models.PositiveSmallIntegerField()
    owner = models.CharField(max_length=200, blank=True)
    condition = models.CharField(max_length=16, choices=Condition.choices, default=Condition.GOOD)
    availability = models.CharField(
        max_length=16, choices=Availability.choices, default=Availability.AVAILABLE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "containers"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "number"], name="containers_number_unique"),
            models.CheckConstraint(
                condition=models.Q(size_ft__in=[10, 20, 40, 45]), name="containers_size_valid"
            ),
        ]


class ContainerEvent(TenantOwnedModel):
    """Append-only movements, inspections and status changes of a container."""

    class Kind(models.TextChoices):
        INSPECTION = "inspection"
        MOVEMENT = "movement"
        STATUS = "status"

    id = models.BigAutoField(primary_key=True)
    container = models.ForeignKey(Container, on_delete=models.PROTECT, related_name="events")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    condition = models.CharField(max_length=16, blank=True)
    location_label = models.CharField(max_length=200, blank=True)
    note = models.TextField(blank=True)
    actor_user_id = models.UUIDField(null=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "container_events"
