"""events public interface: write business events to the outbox (D-014).

Call ``emit()`` inside the transaction that makes the change. High-frequency GPS never goes
through the outbox (MASTER_PROMPT §4.1); only the business events listed in EVENT_TYPES do.
"""

from __future__ import annotations

from typing import Any

from corridor.core.request_context import current_request_id
from corridor.events.models import OutboxEvent

EVENT_TYPES = frozenset(
    {
        "tenant.created",
        "shipment.created",
        "shipment.confirmed",
        "shipment.dispatched",
        "shipment.delayed",
        "shipment.delivered",
        "trip.created",
        "trip.assigned",
        "trip.started",
        "trip.completed",
        "tracking.session.started",
        "tracking.session.stopped",
        "checkpoint.reached",
        "border.arrived",
        "border.clearance.confirmed",
        "route.deviation.detected",
    }
)


def emit(event_type: str, *, aggregate_type: str, aggregate_id: Any, payload: dict[str, Any]) -> int:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    event = OutboxEvent.for_context(
        type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload=payload,
        request_id=current_request_id() or "",
    )
    event.save()
    return int(event.id)
