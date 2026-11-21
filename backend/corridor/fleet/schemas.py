"""fleet public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class VehicleIn(_In):
    plate: str = Field(min_length=2, max_length=20)
    kind: Literal["tractor", "rigid"] = "tractor"
    make: str = Field(default="", max_length=60)
    model: str = Field(default="", max_length=60)
    year: int | None = Field(default=None, ge=1950, le=2100)


class VehicleUpdateIn(_In):
    make: str | None = Field(default=None, max_length=60)
    model: str | None = Field(default=None, max_length=60)
    year: int | None = Field(default=None, ge=1950, le=2100)


class TrailerIn(_In):
    plate: str = Field(min_length=2, max_length=20)
    kind: str = Field(default="", max_length=32)


class AssetStatusIn(_In):
    status: Literal["available", "maintenance", "retired"]
    reason: str = Field(default="", max_length=500)


class VehicleOut(Schema):
    id: uuid.UUID
    plate: str
    kind: str
    make: str
    model: str
    year: int | None
    status: str
    assigned_trip_id: uuid.UUID | None = None  # derived from the active trip assignment
    created_at: datetime


class TrailerOut(Schema):
    id: uuid.UUID
    plate: str
    kind: str
    status: str
    created_at: datetime


class VehiclePage(Schema):
    items: list[VehicleOut]
    next_cursor: str | None


class TrailerPage(Schema):
    items: list[TrailerOut]
    next_cursor: str | None
