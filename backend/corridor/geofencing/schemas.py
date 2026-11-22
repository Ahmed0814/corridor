"""geofencing public DTOs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field, model_validator


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class LatLng(_In):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


GeofenceKindIn = Literal["port", "border", "city", "depot", "customer_site", "checkpoint"]


class GeofenceIn(_In):
    """Either a circle (``center`` + ``radius_m``) or a polygon (``polygon``: 3 to 200 corners)."""

    name: str = Field(min_length=1, max_length=120)
    kind: GeofenceKindIn
    center: LatLng | None = None
    radius_m: float | None = Field(default=None, ge=50, le=20_000)
    polygon: list[LatLng] | None = Field(default=None, min_length=3, max_length=200)
    source_note: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def _one_shape(self) -> GeofenceIn:
        circle = self.center is not None or self.radius_m is not None
        if circle == (self.polygon is not None):
            raise ValueError("give either center + radius_m, or polygon")
        if circle and (self.center is None or self.radius_m is None):
            raise ValueError("a circle needs both center and radius_m")
        return self


class GeofenceOut(Schema):
    id: uuid.UUID
    name: str
    kind: str
    shape: str
    polygon: list[list[float]]  # [[lng, lat], ...] exterior ring, GeoJSON order
    source_note: str
    verified: bool
    verified_at: datetime | None
    is_active: bool
    created_at: datetime


class CheckpointIn(_In):
    geofence_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    is_border: bool = False


class CheckpointOut(Schema):
    id: uuid.UUID
    geofence_id: uuid.UUID
    geofence_name: str
    name: str
    is_border: bool
    verified: bool
    is_active: bool
    created_at: datetime


class CheckpointVisitOut(Schema):
    id: int
    trip_id: uuid.UUID
    checkpoint_id: uuid.UUID
    checkpoint_name: str
    is_border: bool
    geofence_verified: bool
    entered_at: datetime
    exited_at: datetime | None


@dataclass(frozen=True, slots=True)
class TrustedPoint:
    """A stored GPS point without blocking flags (tracking hands these over, oldest first)."""

    event_id: uuid.UUID
    lat: float
    lng: float
    recorded_at: datetime
