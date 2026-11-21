"""tenants Pydantic/Ninja schemas (public DTOs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Field, Schema
from pydantic import ConfigDict


class TenantInfo(Schema):
    id: uuid.UUID
    slug: str
    name: str
    status: str
    is_demo: bool


class TenantProfile(TenantInfo):
    settings: dict[str, Any]
    created_at: datetime


class TenantUpdateIn(Schema):
    """Company-editable fields. `status` and `slug` are platform-only and not accepted here."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict[str, Any] | None = None


class TenantCreateIn(Schema):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
    name: str = Field(min_length=1, max_length=200)
    owner_email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    owner_display_name: str = Field(default="", max_length=200)
    is_demo: bool = False
