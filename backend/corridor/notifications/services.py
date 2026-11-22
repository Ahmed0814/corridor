"""notifications public interface (MASTER_PROMPT §3 item 14, D-069).

Requests never send notifications: they write outbox events in their transaction. The worker
receives each event (events.tasks.dispatch_event) and calls ``handle_event`` under the event's
tenant context. Handlers are idempotent (unique per recipient + source event), because delivery is
at-least-once.

Email: real sending needs explicit approval (MASTER_PROMPT §0.3). Unless EMAIL_SENDING_ENABLED is
true, every email is recorded in the email log as ``suppressed`` and only written to the configured
development backend (console / test outbox); SES needs credentials (Phase 7).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from corridor.core.lifecycle import not_found
from corridor.identity.schemas import RequestContext
from corridor.notifications.models import EmailLog, Notification
from corridor.notifications.schemas import NotificationOut, NotificationPage

log = structlog.get_logger(__name__)

# What each business event means for people. Only these events notify anyone.
TEMPLATES: dict[str, dict[str, str]] = {
    "shipment.dispatched": {
        "title": "Shipment {reference} dispatched",
        "body": "It has been assigned to a truck.",
    },
    "shipment.delivered": {"title": "Shipment {reference} delivered", "body": "Delivery confirmed."},
    "shipment.delayed": {"title": "Shipment {reference} delayed", "body": "Reason: {reason}"},
    "border.arrived": {"title": "Shipment {reference} at {border}", "body": "Waiting for border clearance."},
    "border.clearance.confirmed": {
        "title": "Shipment {reference} cleared {border}",
        "body": "On the way again.",
    },
}
# Customer emails go out for these only (customer-facing milestones).
CUSTOMER_EMAIL_EVENTS = {"shipment.dispatched", "shipment.delivered", "shipment.delayed"}


def _render(event_type: str, payload: dict[str, Any]) -> tuple[str, str]:
    t = TEMPLATES[event_type]
    values = {
        "reference": payload.get("reference", ""),
        "reason": payload.get("reason", ""),
        "border": payload.get("border", "the border"),
    }
    return t["title"].format(**values), t["body"].format(**values)


def handle_event(event: dict[str, Any]) -> dict[str, int]:
    """Called by the worker under tenant_context(event tenant). Safe to run more than once."""
    etype = event["event_type"]
    if etype not in TEMPLATES:
        return {"in_app": 0, "email": 0}
    from corridor.customers import services as customers
    from corridor.identity import services as identity

    payload: dict[str, Any] = event.get("payload") or {}
    title, body = _render(etype, payload)
    link = f"/ops/shipments/{payload['shipment_id']}" if payload.get("shipment_id") else ""
    in_app = 0
    for user_id in identity.office_user_ids_with_permission("shipments.read"):
        try:
            with transaction.atomic():
                Notification.for_context(
                    recipient_user_id=user_id,
                    kind=etype,
                    title=title,
                    body=body,
                    link=link,
                    source_event_id=event["event_id"],
                ).save()
            in_app += 1
        except IntegrityError:
            pass  # already delivered for this event
    email = 0
    if etype in CUSTOMER_EMAIL_EVENTS and payload.get("shipment_id"):
        from corridor.shipments import services as shipments

        customer_id = shipments.customer_id_of(uuid.UUID(payload["shipment_id"]))
        address = customers.email_of(customer_id) if customer_id else None
        if address:
            email = _email(address, title, body, kind=etype, source_event_id=event["event_id"])
    return {"in_app": in_app, "email": email}


def _email(to: str, subject: str, body: str, *, kind: str, source_event_id: int) -> int:
    entry = EmailLog.for_context(
        to_address=to, subject=subject[:200], kind=kind, source_event_id=source_event_id, status="pending"
    )
    try:
        with transaction.atomic():
            entry.save()
    except IntegrityError:
        return 0  # already handled
    approved = settings.EMAIL_SENDING_ENABLED
    try:
        if approved or settings.EMAIL_BACKEND.endswith(("console.EmailBackend", "locmem.EmailBackend")):
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to])
        entry.status = "sent" if approved else "suppressed"
        entry.detail = "" if approved else "real sending not approved (EMAIL_SENDING_ENABLED=false)"
    except Exception as exc:  # the log records the failure; the worker retries on its own
        entry.status, entry.detail = "failed", str(exc)[:300]
        log.warning("email_failed", kind=kind)
    entry.save(update_fields=["status", "detail"])
    return 1


# --------------------------------------------------------------------------- inbox API


def inbox(ctx: RequestContext, *, unread_only: bool, limit: int | None) -> NotificationPage:
    qs = Notification.objects.filter(recipient_user_id=ctx.user_id)
    if unread_only:
        qs = qs.filter(read_at__isnull=True)
    rows = list(qs.order_by("-created_at")[: min(max(limit or 50, 1), 200)])
    unread = Notification.objects.filter(recipient_user_id=ctx.user_id, read_at__isnull=True).count()
    return NotificationPage(
        items=[NotificationOut.model_validate(n, from_attributes=True) for n in rows], unread=unread
    )


def mark_read(ctx: RequestContext, notification_id: uuid.UUID) -> NotificationOut:
    n = (
        Notification.objects.select_for_update()
        .filter(id=notification_id, recipient_user_id=ctx.user_id)
        .first()
    )
    if n is None:
        raise not_found()
    if n.read_at is None:
        n.read_at = timezone.now()
        n.save(update_fields=["read_at"])
    return NotificationOut.model_validate(n, from_attributes=True)


def mark_all_read(ctx: RequestContext) -> int:
    return Notification.objects.filter(recipient_user_id=ctx.user_id, read_at__isnull=True).update(
        read_at=timezone.now()
    )
