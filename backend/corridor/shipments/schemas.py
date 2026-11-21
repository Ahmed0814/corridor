"""shipments public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

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
    recipient_name: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=1000)


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
