"""shipments models. A shipment is a cargo movement / customer transaction (MASTER_PROMPT §3).

Status changes only happen through shipments.services transition functions; every change appends
an immutable ShipmentEvent (hard rule 5). Containers ride on a shipment, never on a trip directly.
"""

from __future__ import annotations

import uuid

from django.contrib.gis.db import models as gis
from django.db import models

from corridor.core.tenancy import TenantOwnedModel


class ShipmentStatus(models.TextChoices):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    DISPATCHED = "dispatched"
    IN_TRANSIT = "in_transit"
    AT_BORDER = "at_border"
    DELIVERED = "delivered"
    DELIVERY_FAILED = "delivery_failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = (
    ShipmentStatus.CONFIRMED,
    ShipmentStatus.DISPATCHED,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.AT_BORDER,
    ShipmentStatus.DELIVERY_FAILED,
)


class Shipment(TenantOwnedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=40)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=ShipmentStatus.choices, default=ShipmentStatus.DRAFT)
    is_delayed = models.BooleanField(default=False)
    delay_reason = models.CharField(max_length=300, blank=True)
    cargo_description = models.TextField(blank=True)
    weight_grams = models.BigIntegerField(null=True, blank=True)
    dimensions = models.JSONField(default=dict, blank=True)  # {"length_cm":..,"width_cm":..,"height_cm":..}
    origin_label = models.CharField(max_length=200)
    origin_point = gis.PointField(srid=4326, null=True, blank=True)
    destination_label = models.CharField(max_length=200)
    destination_point = gis.PointField(srid=4326, null=True, blank=True)
    # Deterministic ETA (D-068): recomputed from the latest trusted GPS point; never AI.
    eta = models.DateTimeField(null=True, blank=True)
    eta_method = models.CharField(max_length=32, blank=True)
    eta_computed_at = models.DateTimeField(null=True, blank=True)
    eta_basis_recorded_at = models.DateTimeField(null=True, blank=True)  # GPS point the ETA is based on
    eta_remaining_km = models.FloatField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    recipient_name = models.CharField(max_length=200, blank=True)
    created_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "shipments"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "reference"], name="shipments_reference_unique"),
            models.CheckConstraint(
                condition=models.Q(status__in=[s.value for s in ShipmentStatus]),
                name="shipments_status_valid",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "status"], name="shipments_tenant_status_idx")]


class ShipmentContainer(TenantOwnedModel):
    """A container on a shipment. While ``released_at`` is null the container is on that shipment,
    and a partial unique index guarantees it is on at most one shipment at a time."""

    id = models.BigAutoField(primary_key=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="container_links")
    container = models.ForeignKey("containers.Container", on_delete=models.PROTECT, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "shipment_containers"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "container"],
                condition=models.Q(released_at__isnull=True),
                name="one_active_shipment_per_container",
            ),
            models.UniqueConstraint(fields=["shipment", "container"], name="shipment_container_once"),
        ]


class ShipmentEvent(TenantOwnedModel):
    """Append-only history (the app role has SELECT/INSERT only, D-018)."""

    id = models.BigAutoField(primary_key=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="events")
    type = models.CharField(max_length=40)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20, blank=True)
    actor_kind = models.CharField(max_length=16)
    actor_user_id = models.UUIDField(null=True)
    reason = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shipment_events"
        indexes = [models.Index(fields=["shipment", "id"], name="shipment_events_by_shipment")]


class TrackingLink(TenantOwnedModel):
    """A public, revocable, expiring link to one shipment (D-017, security-model.md §6).

    Only ``sha256(token)`` is stored; the token is shown once. The public endpoint resolves it
    through the SECURITY DEFINER function ``public_resolve_tracking_link`` and exposes only the
    ``allowed_fields``.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shipment = models.ForeignKey(Shipment, on_delete=models.PROTECT, related_name="tracking_links")
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120, blank=True)
    allowed_fields = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.UUIDField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=300, blank=True)
    created_by = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tracking_links"
        indexes = [models.Index(fields=["tenant", "shipment"], name="tracking_links_by_shipment")]
