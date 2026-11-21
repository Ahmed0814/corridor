"""drivers public DTOs. ``license_number`` is only filled for callers with drivers.pii."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from ninja import Schema
from pydantic import ConfigDict, Field

PHONE = r"^\+[1-9]\d{6,14}$"


class _In(Schema):
    model_config = ConfigDict(extra="forbid")


class DriverIn(_In):
    full_name: str = Field(min_length=1, max_length=200)
    phone_e164: str = Field(default="", pattern=rf"(^$)|{PHONE}")
    license_number: str = Field(default="", max_length=40)
    license_expiry: date | None = None


class DriverUpdateIn(_In):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    phone_e164: str | None = Field(default=None, pattern=rf"(^$)|{PHONE}")
    license_number: str | None = Field(default=None, max_length=40)
    license_expiry: date | None = None
    employment_status: Literal["active", "inactive", "terminated"] | None = None


class ConsentIn(_In):
    tracking_consent: bool


class LinkMembershipIn(_In):
    membership_id: uuid.UUID


class DriverOut(Schema):
    id: uuid.UUID
    full_name: str
    phone_e164: str | None  # personal data: null without drivers.pii (own profile excepted)
    license_number: str | None  # personal data: null without drivers.pii (own profile excepted)
    license_expiry: date | None
    employment_status: str
    tracking_consent: bool
    tracking_consent_at: datetime | None
    membership_id: uuid.UUID | None
    created_at: datetime


class DriverPage(Schema):
    items: list[DriverOut]
    next_cursor: str | None
