"""events Celery tasks: heartbeat, outbox relay and event dispatch (D-009, D-014, D-051)."""

from __future__ import annotations

from typing import Any

import structlog
from celery import shared_task
from django.db import connections, transaction

log = structlog.get_logger(__name__)

RELAY_DB = "relay"
RELAY_BATCH = 100


@shared_task(name="corridor.events.tasks.heartbeat")
def heartbeat() -> str:
    """Scheduled by beat every 60 s; proves the scheduler -> broker -> worker path."""
    log.info("celery_heartbeat")
    return "ok"


# Handlers per event type, run by the worker. Each must be idempotent (at-least-once delivery).
# Notifications, realtime fan-out and ETA recomputation register here in later phases.
HANDLERS: dict[str, list[str]] = {}


def relay_once(batch: int = RELAY_BATCH) -> int:
    """Publish unpublished outbox rows, oldest first; returns how many were published.

    Runs on the ``relay`` connection (role corridor_relay), whose RLS policy exposes exactly this
    table across tenants. ``FOR UPDATE SKIP LOCKED`` lets concurrent relays share the work without
    double-publishing. A row is marked published only after the broker accepted the message.
    """
    published = 0
    with transaction.atomic(using=RELAY_DB), connections[RELAY_DB].cursor() as cursor:
        cursor.execute(
            "SELECT id, tenant_id, type, aggregate_type, aggregate_id, payload, request_id "
            "FROM outbox_events WHERE published_at IS NULL ORDER BY id "
            "LIMIT %s FOR UPDATE SKIP LOCKED",
            [batch],
        )
        rows = cursor.fetchall()
        for event_id, tenant_id, etype, agg_type, agg_id, payload, request_id in rows:
            try:
                dispatch_event.apply_async(
                    kwargs={
                        "event_id": event_id,
                        "tenant_id": str(tenant_id),
                        "event_type": etype,
                        "aggregate_type": agg_type,
                        "aggregate_id": agg_id,
                        "payload": payload,
                    },
                    headers={"request_id": request_id} if request_id else {},
                )
            except Exception:
                log.exception("outbox_publish_failed", event_id=event_id, event_type=etype)
                cursor.execute("UPDATE outbox_events SET attempts = attempts + 1 WHERE id = %s", [event_id])
                continue
            cursor.execute(
                "UPDATE outbox_events SET published_at = now(), attempts = attempts + 1 WHERE id = %s",
                [event_id],
            )
            published += 1
    if published:
        log.info("outbox_relayed", count=published)
    return published


@shared_task(name="corridor.events.tasks.relay_outbox")
def relay_outbox() -> int:
    return relay_once()


@shared_task(name="corridor.events.tasks.dispatch_event", acks_late=True)
def dispatch_event(
    *,
    event_id: int,
    tenant_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> int:
    """Fan an outbox event out to its handlers (none registered yet in Phase 3)."""
    handlers = HANDLERS.get(event_type, [])
    log.info("event_dispatched", event_id=event_id, event_type=event_type, handlers=len(handlers))
    return len(handlers)
