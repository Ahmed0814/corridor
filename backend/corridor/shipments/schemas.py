"""shipments public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from ninja import Schema
from pydantic import ConfigDict, Field


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class GeoPoint(Schema):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class ShipmentIn(_In):
    reference: str | None = Field(default=None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._/-]+$")
    customer_id: uuid.UUID
    cargo_description: str = Field(default="", max_length=4000)
    weight_kg: float | None = Field(default=None, ge=0, le=200_000)
    dimensions: dict[str, float] = Field(default_factory=dict)
    origin_label: str = Field(min_length=1, max_length=200)
    origin: GeoPoint | None = None
    destination_label: str = Field(min_length=1, max_length=200)
    destination: GeoPoint | None = None
    container_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class ShipmentUpdateIn(_In):
    """Only drafts can be edited; after confirmation changes go through transitions/corrections."""

    cargo_description: str | None = Field(default=None, max_length=4000)
    weight_kg: float | None = Field(default=None, ge=0, le=200_000)
    dimensions: dict[str, float] | None = None
    origin_label: str | None = Field(default=None, min_length=1, max_length=200)
    origin: GeoPoint | None = None
    destination_label: str | None = Field(default=None, min_length=1, max_length=200)
    destination: GeoPoint | None = None
    container_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)


class ReasonIn(_In):
    reason: str = Field(min_length=1, max_length=1000)


class OptionalReasonIn(_In):
    reason: str = Field(default="", max_length=1000)


class BorderIn(_In):
    border: str = Field(min_length=1, max_length=100, description="e.g. Galafi, Dewele")
    note: str = Field(default="", max_length=1000)


class DeliverIn(_In):
    """Proof of delivery (Phase 6): at least one delivery photo and the recipient's signature, both
    uploaded first to POST /shipments/{id}/documents."""

    recipient_name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)
    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    signature_id: uuid.UUID


class CorrectionIn(_In):
    to_status: str = Field(
        pattern=r"^(draft|confirmed|dispatched|in_transit|at_border|delivered|delivery_failed|cancelled)$"
    )
    reason: str = Field(min_length=1, max_length=1000)


class ContainerRef(Schema):
    id: uuid.UUID
    number: str


class ShipmentOut(Schema):
    id: uuid.UUID
    reference: str
    customer_id: uuid.UUID
    customer_name: str | None
    status: str
    is_delayed: bool
    delay_reason: str
    cargo_description: str
    weight_kg: float | None
    dimensions: dict[str, Any]
    origin_label: str
    origin: GeoPoint | None
    destination_label: str
    destination: GeoPoint | None
    eta: datetime | None
    eta_method: str
    eta_remaining_km: float | None
    eta_basis_recorded_at: datetime | None
    delivered_at: datetime | None
    recipient_name: str
    containers: list[ContainerRef]
    trip_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class ShipmentEventOut(Schema):
    id: int
    type: str
    from_status: str
    to_status: str
    actor_kind: str
    actor_user_id: uuid.UUID | None
    reason: str
    payload: dict[str, Any]
    occurred_at: datetime


class ShipmentPage(Schema):
    items: list[ShipmentOut]
    next_cursor: str | None


# ---------------------------------------------------------------- public tracking links (Phase 6)

LinkField = Literal["status", "eta", "route", "timeline", "position", "delivery"]


class TrackingLinkIn(_In):
    label: str = Field(default="", max_length=120)
    expires_in_days: int = Field(default=30, ge=1, le=90)
    allowed_fields: list[LinkField] | None = None  # default: all public fields


class TrackingLinkOut(Schema):
    id: uuid.UUID
    shipment_id: uuid.UUID
    label: str
    allowed_fields: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    state: Literal["active", "expired", "revoked"]
    created_at: datetime


class TrackingLinkCreated(TrackingLinkOut):
    token: str  # shown once; only its hash is stored


class PublicPosition(Schema):
    latitude: float
    longitude: float
    precision_km: float
    recorded_at: datetime
    received_at: datetime
    freshness: str


class ShipmentPositionOut(Schema):
    """Approximate position while the shipment is on the road; null otherwise."""

    position: PublicPosition | None


class PublicTimelineItem(Schema):
    label: str
    at: datetime


class PublicTracking(Schema):
    """Only fields the link allows; nothing about drivers, vehicles or internal actors."""

    reference: str
    status: str | None = None
    is_delayed: bool | None = None
    origin_label: str | None = None
    destination_label: str | None = None
    eta: datetime | None = None
    eta_method: str | None = None
    delivered_at: datetime | None = None
    timeline: list[PublicTimelineItem] | None = None
    position: PublicPosition | None = None
