"""containers public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class ContainerIn(_In):
    number: str = Field(min_length=11, max_length=13, description="ISO 6346, e.g. MSCU1234565")
    iso_type: str = Field(default="", max_length=4)
    size_ft: Literal[10, 20, 40, 45]
    owner: str = Field(default="", max_length=200)
    condition: Literal["good", "damaged", "needs_repair"] = "good"


class ContainerUpdateIn(_In):
    iso_type: str | None = Field(default=None, max_length=4)
    owner: str | None = Field(default=None, max_length=200)


class AvailabilityIn(_In):
    availability: Literal["available", "maintenance", "retired"]
    reason: str = Field(default="", max_length=500)


class InspectionIn(_In):
    condition: Literal["good", "damaged", "needs_repair"]
    location_label: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2000)


class ContainerOut(Schema):
    id: uuid.UUID
    number: str
    iso_type: str
    size_ft: int
    owner: str
    condition: str
    availability: str
    created_at: datetime
    updated_at: datetime


class ContainerEventOut(Schema):
    id: int
    kind: str
    condition: str
    location_label: str
    note: str
    actor_user_id: uuid.UUID | None
    occurred_at: datetime


class ContainerPage(Schema):
    items: list[ContainerOut]
    next_cursor: str | None
