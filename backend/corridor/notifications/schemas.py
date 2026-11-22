"""notifications public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema


class NotificationOut(Schema):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str
    read_at: datetime | None
    created_at: datetime


class NotificationPage(Schema):
    items: list[NotificationOut]
    unread: int
