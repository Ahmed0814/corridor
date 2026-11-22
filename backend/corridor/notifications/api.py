"""notifications Ninja router: the signed-in user's own in-app inbox."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router

from corridor.core.idempotency import idempotent
from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.notifications import services
from corridor.notifications.schemas import NotificationOut, NotificationPage

router = Router(tags=["notifications"], auth=tenant_auth)


@router.get("/notifications", response=NotificationPage, summary="My notifications (newest first)")
@requires("tenant.read")
def inbox(request: HttpRequest, unread: bool = False, limit: int | None = None) -> NotificationPage:
    return services.inbox(ctx_of(request), unread_only=unread, limit=limit)


@router.post("/notifications/{notification_id}/read", response=NotificationOut, summary="Mark as read")
@requires("tenant.read")
@idempotent
def mark_read(request: HttpRequest, notification_id: uuid.UUID) -> NotificationOut:
    return services.mark_read(ctx_of(request), notification_id)


@router.post("/notifications/read-all", response=dict[str, int], summary="Mark all as read")
@requires("tenant.read")
@idempotent
def mark_all_read(request: HttpRequest) -> dict[str, int]:
    return {"marked": services.mark_all_read(ctx_of(request))}
