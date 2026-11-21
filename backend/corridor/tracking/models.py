"""tracking models (MASTER_PROMPT §4.1, DECISIONS D-011, D-012, D-013).

* ``TrackingSession``: one per started trip; GPS is only accepted inside an authorized session.
* ``GpsLocationEvent``: the append-only, monthly-partitioned history. The table is created by raw
  SQL in the migration (partitioning, BRIN, composite dedupe key); this model is unmanaged and used
  for reads only. Inserts go through ``tracking.services`` with ``ON CONFLICT DO NOTHING``.
* ``VehicleLatestLocation``: the latest *trusted* point per vehicle, updated only by a conditional
  upsert that never lets an older event overwrite a newer one (hard rule 4).
"""

from __future__ import annotations

import uuid

from django.contrib.gis.db import models as gis
from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class SessionStatus(models.TextChoices):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class TrackingSession(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="+")
    driver = models.ForeignKey("drivers.Driver", on_delete=models.PROTECT, related_name="+")
    vehicle = models.ForeignKey("fleet.Vehicle", on_delete=models.PROTECT, related_name="+")
    # The driver's phone install, bound by the first accepted upload (D-057).
    device_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=SessionStatus.choices, default=SessionStatus.ACTIVE)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tracking_sessions"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "trip"],
                condition=~models.Q(status="closed"),
                name="one_open_session_per_trip",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "trip", "driver"], name="tracking_sessions_trip_driver")]


class Flag:
    """Validation flags stored on each event (bitmask, docs/database/erd.md)."""

    LOW_ACCURACY = 1
    OUT_OF_ORDER = 2
    IMPOSSIBLE_SPEED = 4
    CLOCK_SKEW = 8
    WHILE_PAUSED = 16
    LATE_UPLOAD = 32
    NETWORK_FIX = 64

    NAMES = {
        LOW_ACCURACY: "low_accuracy",
        OUT_OF_ORDER: "out_of_order",
        IMPOSSIBLE_SPEED: "impossible_speed",
        CLOCK_SKEW: "clock_skew",
        WHILE_PAUSED: "while_paused",
        LATE_UPLOAD: "late_upload",
        NETWORK_FIX: "network_fix",
    }
    # Flags that keep an event out of the latest trusted location.
    BLOCKING = LOW_ACCURACY | OUT_OF_ORDER | IMPOSSIBLE_SPEED | CLOCK_SKEW

    @classmethod
    def names(cls, flags: int) -> list[str]:
        return [name for bit, name in cls.NAMES.items() if flags & bit]


class GpsLocationEvent(TenantOwnedModel):
    """Read model over the partitioned ``gps_location_events`` table (append-only)."""

    id = models.BigIntegerField(primary_key=True)
    event_id = models.UUIDField()
    device_id = models.UUIDField()
    session_id = models.UUIDField()
    trip_id = models.UUIDField()
    vehicle_id = models.UUIDField()
    driver_id = models.UUIDField()
    sequence_number = models.BigIntegerField(null=True)
    point = gis.PointField(srid=4326)
    accuracy_m = models.FloatField(null=True)
    speed_mps = models.FloatField(null=True)
    heading_deg = models.FloatField(null=True)
    recorded_at = models.DateTimeField()
    received_at = models.DateTimeField()
    source = models.CharField(max_length=16)
    flags = models.IntegerField()

    class Meta:
        managed = False
        db_table = "gps_location_events"


class VehicleLatestLocation(TenantOwnedModel):
    vehicle = models.OneToOneField(
        "fleet.Vehicle", on_delete=models.CASCADE, primary_key=True, related_name="+"
    )
    event_id = models.UUIDField()
    trip_id = models.UUIDField(null=True)
    session_id = models.UUIDField(null=True)
    driver_id = models.UUIDField(null=True)
    point = gis.PointField(srid=4326)
    accuracy_m = models.FloatField(null=True)
    speed_mps = models.FloatField(null=True)
    heading_deg = models.FloatField(null=True)
    recorded_at = models.DateTimeField()
    received_at = models.DateTimeField()
    source = models.CharField(max_length=16)

    class Meta:
        db_table = "vehicle_latest_locations"
