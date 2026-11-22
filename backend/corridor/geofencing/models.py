"""geofencing models (MASTER_PROMPT §3 item 10, docs/database/erd.md §3, DECISIONS D-027, D-067).

* ``Geofence``: an area drawn by a tenant operator (polygon, or a circle stored as a polygon).
  It starts unverified; an authorized operator must verify it before GPS entry into a *border*
  geofence may change a shipment's status (D-027).
* ``Checkpoint``: a geofence that is watched on every trip of the tenant (``is_border`` marks
  border crossings such as Galafi or Dewele).
* ``CheckpointVisit``: one entry/exit of a trip into a checkpoint, detected from trusted GPS points.
"""

from __future__ import annotations

import uuid

from django.contrib.gis.db import models as gis
from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class GeofenceKind(models.TextChoices):
    PORT = "port"
    BORDER = "border"
    CITY = "city"
    DEPOT = "depot"
    CUSTOMER_SITE = "customer_site"
    CHECKPOINT = "checkpoint"


class Geofence(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    kind = models.CharField(max_length=16, choices=GeofenceKind.choices)
    area = gis.PolygonField(srid=4326)  # spatial (GiST) index by default
    shape = models.CharField(max_length=8, default="polygon")  # polygon | circle (how it was drawn)
    source_note = models.CharField(max_length=300, blank=True)  # where the outline came from
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.UUIDField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "geofences"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "name"], name="geofences_name_unique"),
            models.CheckConstraint(
                condition=models.Q(kind__in=[k.value for k in GeofenceKind]), name="geofences_kind_valid"
            ),
        ]


class Checkpoint(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    geofence = models.ForeignKey(Geofence, on_delete=models.PROTECT, related_name="checkpoints")
    name = models.CharField(max_length=120)
    is_border = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "checkpoints"
        constraints = [models.UniqueConstraint(fields=["tenant", "name"], name="checkpoints_name_unique")]


class CheckpointVisit(TenantOwnedModel):
    """While ``exited_at`` is null the trip is inside the checkpoint (at most one open visit each)."""

    id = models.BigAutoField(primary_key=True)
    trip = models.ForeignKey("trips.Trip", on_delete=models.PROTECT, related_name="+")
    checkpoint = models.ForeignKey(Checkpoint, on_delete=models.PROTECT, related_name="visits")
    vehicle_id = models.UUIDField()
    entered_at = models.DateTimeField()  # recorded_at of the first trusted point inside
    entry_event_id = models.UUIDField()
    exited_at = models.DateTimeField(null=True, blank=True)  # recorded_at of the first point outside
    exit_event_id = models.UUIDField(null=True, blank=True)
    geofence_verified = models.BooleanField()  # verification state at entry time (kept for history)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "checkpoint_visits"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "trip", "checkpoint"],
                condition=models.Q(exited_at__isnull=True),
                name="one_open_visit_per_trip_checkpoint",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "trip", "entered_at"], name="checkpoint_visits_by_trip")]
