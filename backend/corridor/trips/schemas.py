"""trips public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class TripIn(_In):
    reference: str | None = Field(default=None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9._/-]+$")
    origin_label: str = Field(min_length=1, max_length=200)
    destination_label: str = Field(min_length=1, max_length=200)
    planned_start: datetime | None = None
    shipment_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)


class AssignIn(_In):
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID
    trailer_id: uuid.UUID | None = None


class ActionIn(_In):
    """Driver actions on their own trip need no reason; acting on behalf of the driver does."""

    reason: str = Field(default="", max_length=1000)


class ReasonIn(_In):
    reason: str = Field(min_length=1, max_length=1000)


class TripCorrectionIn(_In):
    to_status: str = Field(pattern=r"^(planned|assigned|in_progress|paused|completed|cancelled|aborted)$")
    reason: str = Field(min_length=1, max_length=1000)


class AssignmentOut(Schema):
    id: uuid.UUID
    vehicle_id: uuid.UUID
    vehicle_plate: str | None
    driver_id: uuid.UUID
    driver_name: str | None
    trailer_id: uuid.UUID | None
    status: str
    created_at: datetime
    released_at: datetime | None


class TripOut(Schema):
    id: uuid.UUID
    reference: str
    status: str
    mode: str
    origin_label: str
    destination_label: str
    planned_start: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    shipment_ids: list[uuid.UUID]
    assignment: AssignmentOut | None  # the active one
    created_at: datetime
    updated_at: datetime


class TripEventOut(Schema):
    id: int
    type: str
    from_status: str
    to_status: str
    actor_kind: str
    actor_user_id: uuid.UUID | None
    reason: str
    payload: dict[str, Any]
    occurred_at: datetime


class TripPage(Schema):
    items: list[TripOut]
    next_cursor: str | None


class DispatchPlanIn(_In):
    """One-step dispatch: create a trip for confirmed shipments, assign vehicle + driver, dispatch."""

    shipment_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    vehicle_id: uuid.UUID
    driver_id: uuid.UUID
    trailer_id: uuid.UUID | None = None
    origin_label: str = Field(min_length=1, max_length=200)
    destination_label: str = Field(min_length=1, max_length=200)
    planned_start: datetime | None = None
