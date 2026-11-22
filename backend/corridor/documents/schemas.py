"""documents public DTOs."""

from __future__ import annotations

import uuid
from datetime import datetime

from ninja import Schema


class DocumentOut(Schema):
    id: uuid.UUID
    shipment_id: uuid.UUID
    kind: str
    content_type: str
    size_bytes: int
    sha256: str
    original_name: str
    visibility: str
    created_at: datetime
