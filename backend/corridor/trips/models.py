"""trips models. A trip is an actual journey; one shipment may use several trips (MASTER_PROMPT §3).

Trip assignments live here (not in ``dispatch``) because the trip lifecycle depends on them at every
step; ``dispatch`` orchestrates planning across modules through services (DECISIONS D-052).
"""

from __future__ import annotations

import uuid

from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class TripStatus(models.TextChoices):
    PLANNED = "planned"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ABORTED = "aborted"


OPEN_STATUSES = (TripStatus.PLANNED, TripStatus.ASSIGNED, TripStatus.IN_PROGRESS, TripStatus.PAUSED)


class Trip(TenantOwnedModel):
    class Mode(models.TextChoices):
        ROAD = "road"  # rail is post-pilot (D-026)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=40)
    status = models.CharField(max_length=16, choices=TripStatus.choices, default=TripStatus.PLANNED)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.ROAD)
    origin_label = models.CharField(max_length=200)
    destination_label = models.CharField(max_length=200)
    planned_start = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "trips"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="trips_reference_unique"),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in TripStatus]), name="trips_status_valid"
            ),
        ]


class TripShipment(TenantOwnedModel):
    """Which shipments a trip moves (many-to-many: consolidation and multi-leg shipments)."""

    id = models.BigAutoField(primary_key=True)
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="shipment_links")
    shipment = models.ForeignKey("shipments.Shipment", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trip_shipments"
        constraints = [models.UniqueConstraint(fields=["trip", "shipment"], name="trip_shipment_once")]


class TripAssignment(TenantOwnedModel):
    class Status(models.TextChoices):
        ACTIVE = "active"
        RELEASED = "released"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="assignments")
    vehicle = models.ForeignKey("fleet.Vehicle", on_delete=models.PROTECT, related_name="+")
    driver = models.ForeignKey("drivers.Driver", on_delete=models.PROTECT, related_name="+")
    trailer = models.ForeignKey(
        "fleet.Trailer", on_delete=models.PROTECT, related_name="+", null=True, blank=True
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    assigned_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "trip_assignments"
        # The database is the final arbiter of conflicting assignments (concurrent dispatch race).
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "vehicle"],
                condition=models.Q(status="active"),
                name="one_active_assignment_per_vehicle",
            ),
            models.UniqueConstraint(
                fields=["tenant", "driver"],
                condition=models.Q(status="active"),
                name="one_active_assignment_per_driver",
            ),
            models.UniqueConstraint(
                fields=["tenant", "trailer"],
                condition=models.Q(status="active", trailer__isnull=False),
                name="one_active_assignment_per_trailer",
            ),
            models.UniqueConstraint(
                fields=["tenant", "trip"],
                condition=models.Q(status="active"),
                name="one_active_assignment_per_trip",
            ),
        ]


class TripEvent(TenantOwnedModel):
    """Append-only history (SELECT/INSERT only for the app role, D-018)."""

    id = models.BigAutoField(primary_key=True)
    trip = models.ForeignKey(Trip, on_delete=models.PROTECT, related_name="events")
    type = models.CharField(max_length=40)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    actor_kind = models.CharField(max_length=16)
    actor_user_id = models.UUIDField(null=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "trip_events"
        indexes = [models.Index(fields=["trip", "id"], name="trip_events_by_trip")]
