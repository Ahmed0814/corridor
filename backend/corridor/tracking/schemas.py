"""tracking public DTOs.

Coordinates, accuracy and timestamps are validated per event in the service (not by Pydantic), so
one bad point is rejected with a reason while the rest of the batch is still accepted.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field


class LocationIn(Schema):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    device_id: uuid.UUID
    trip_id: uuid.UUID
    vehicle_id: uuid.UUID
    sequence_number: int | None = None
    latitude: float
    longitude: float
    accuracy_meters: float | None = None
    speed: float | None = Field(default=None, description="metres per second")
    heading: float | None = None
    recorded_at: datetime
    source: Literal["phone_gps", "phone_network", "telematics"] = "phone_gps"


class LocationBatchIn(Schema):
    model_config = ConfigDict(extra="forbid")
    events: list[LocationIn] = Field(min_length=1, max_length=500)


class Rejected(Schema):
    event_id: uuid.UUID
    reason: str


class IngestResult(Schema):
    """What the app needs to clear its local queue: delete accepted + duplicate, keep rejected."""

    accepted: list[uuid.UUID]
    duplicate: list[uuid.UUID]
    rejected: list[Rejected]
    flagged: dict[str, list[str]]  # event_id -> validation flags (stored, never trusted as latest)


class LatestLocationOut(Schema):
    vehicle_id: uuid.UUID
    vehicle_plate: str | None
    trip_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    latitude: float
    longitude: float
    accuracy_meters: float | None
    speed: float | None
    heading: float | None
    recorded_at: datetime  # always shown together with received_at (hard rule 3)
    received_at: datetime
    source: str
    freshness: Literal["live", "delayed", "stale", "offline"]
    age_seconds: int
    session_active: bool


class TrackPointOut(Schema):
    event_id: uuid.UUID
    latitude: float
    longitude: float
    accuracy_meters: float | None
    speed: float | None
    heading: float | None
    recorded_at: datetime
    received_at: datetime
    source: str
    flags: list[str]


class TrackOut(Schema):
    trip_id: uuid.UUID
    points: list[TrackPointOut]
    next_after: datetime | None


class FleetOut(Schema):
    vehicles: list[LatestLocationOut]
    thresholds: dict[str, int]
    generated_at: datetime
