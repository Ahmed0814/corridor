"""customers public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema
from pydantic import ConfigDict, Field

PHONE = r"^\+[1-9]\d{6,14}$"


class _In(Schema):
    model_config = ConfigDict(extra="forbid")  # unknown fields (e.g. tenant_id) are rejected


class CustomerIn(_In):
    name: str = Field(min_length=1, max_length=200)
    tax_id: str = Field(default="", max_length=64)
    email: str = Field(default="", max_length=254)
    phone_e164: str = Field(default="", pattern=rf"(^$)|{PHONE}")
    address: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=4000)


class CustomerUpdateIn(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=254)
    phone_e164: str | None = Field(default=None, pattern=rf"(^$)|{PHONE}")
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern=r"^(active|inactive)$")


class ContactIn(_In):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="", max_length=100)
    email: str = Field(default="", max_length=254)
    phone_e164: str = Field(default="", pattern=rf"(^$)|{PHONE}")


class ContactOut(Schema):
    id: uuid.UUID
    name: str
    role: str
    email: str
    phone_e164: str


class CustomerOut(Schema):
    id: uuid.UUID
    name: str
    tax_id: str
    email: str
    phone_e164: str
    address: str
    notes: str
    status: str
    created_at: datetime
    updated_at: datetime


class CustomerDetail(CustomerOut):
    contacts: list[ContactOut]


class PortalUserLinkIn(_In):
    membership_id: uuid.UUID


class CustomerPage(Schema):
    items: list[CustomerOut]
    next_cursor: str | None
