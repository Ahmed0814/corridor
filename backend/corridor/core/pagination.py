"""Cursor (keyset) pagination for list endpoints (docs/architecture/overview.md §5).

Ordering is (created_at DESC, id DESC); the cursor encodes the last row's pair, so pages are stable
while rows are inserted and no OFFSET scan is needed. Cursors are opaque to clients.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from typing import Any

from django.db import models

from corridor.core.api import ApiError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _encode(created_at: datetime, pk: Any) -> str:
    raw = json.dumps([created_at.isoformat(), str(pk)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created, pk = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(created), str(uuid.UUID(pk))
    except (ValueError, TypeError) as exc:
        raise ApiError(400, "bad_request", "Invalid cursor.") from exc


def paginate(
    queryset: models.QuerySet[Any], cursor: str | None, limit: int | None
) -> tuple[list[Any], str | None]:
    limit = min(max(limit or DEFAULT_LIMIT, 1), MAX_LIMIT)
    qs = queryset.order_by("-created_at", "-id")
    if cursor:
        created_at, pk = _decode(cursor)
        qs = qs.filter(models.Q(created_at__lt=created_at) | models.Q(created_at=created_at, id__lt=pk))
    rows = list(qs[: limit + 1])
    next_cursor = _encode(rows[limit - 1].created_at, rows[limit - 1].pk) if len(rows) > limit else None
    return rows[:limit], next_cursor
