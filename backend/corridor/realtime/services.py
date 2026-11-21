"""realtime public interface. Other modules may import only this file and schemas.py (D-005).

Group names are built here, server-side only (security-model.md §5). A client never sends a
group name; it asks for a topic, and the consumer decides which group that means for its
authenticated tenant.
"""

from __future__ import annotations

import uuid
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def fleet_group(tenant_id: uuid.UUID) -> str:
    return f"t.{tenant_id}.fleet"


def broadcast_fleet(tenant_id: uuid.UUID, payload: dict[str, Any]) -> None:
    """Send a vehicle update to every subscriber of this tenant's fleet topic.

    Call it from transaction.on_commit (non-critical side effect, D-011).
    """
    layer = get_channel_layer()
    if layer is None:
        return
    async_to_sync(layer.group_send)(fleet_group(tenant_id), {"type": "fleet.update", "payload": payload})
