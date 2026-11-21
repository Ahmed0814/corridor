"""audit Pydantic/Ninja schemas (public DTOs)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ninja import Schema


class AuditEntry(Schema):
    id: int
    tenant_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    actor_kind: str
    action: str
    target_type: str
    target_id: str
    metadata: dict[str, Any]
    request_id: str
    occurred_at: datetime
