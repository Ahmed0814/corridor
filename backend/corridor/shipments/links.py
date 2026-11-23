"""Public tracking links for shipments (MASTER_PROMPT §4.4, DECISIONS D-017, security-model.md §6).

* Token: ``secrets.token_urlsafe(32)`` (256 bits), shown ONCE at creation; only ``sha256(token)`` is
  stored.
* Resolution without a tenant context goes through the SECURITY DEFINER function
  ``public_resolve_tracking_link(hash)``, which returns only (tenant_id, shipment_id, allowed_fields)
  for a live link (not revoked, not expired). The request then runs under that tenant's context.
* The public response contains only the link's allowed fields. Position is coarse (≈ 1 km) and shown
  only while the shipment is moving; never driver data, never the vehicle plate.
* Invalid, expired and revoked links all answer the same 404.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from typing import Any, Literal

from django.db import connection
from django.utils import timezone

from corridor.audit import services as audit
from corridor.core.lifecycle import lock, not_found, require_reason
from corridor.core.tenancy import apply_context
from corridor.identity.schemas import RequestContext, Scope
from corridor.shipments.models import Shipment, ShipmentEvent, ShipmentStatus, TrackingLink
from corridor.shipments.schemas import (
    PublicPosition,
    PublicTimelineItem,
    PublicTracking,
    TrackingLinkCreated,
    TrackingLinkIn,
    TrackingLinkOut,
)

ALLOWED = ("status", "eta", "route", "timeline", "position", "delivery")
DEFAULT_FIELDS = list(ALLOWED)
MAX_DAYS = 90
COARSE_DEGREES = 0.01  # ≈ 1.1 km: enough to follow progress, not to find the truck

# Timeline entries a customer may see (no actors, no reasons, no internal events).
PUBLIC_EVENTS = {
    "created": "Shipment created",
    "confirmed": "Confirmed",
    "dispatched": "Dispatched",
    "in_transit": "On the way",
    "border_arrived": "Arrived at the border",
    "border_cleared": "Border cleared",
    "delivery_failed": "Delivery attempt failed",
    "delivery_reattempt": "Delivery re-attempted",
    "delivered": "Delivered",
    "cancelled": "Cancelled",
}
MOVING = (ShipmentStatus.DISPATCHED, ShipmentStatus.IN_TRANSIT, ShipmentStatus.AT_BORDER)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _out(link: TrackingLink) -> TrackingLinkOut:
    now = timezone.now()
    state: Literal["active", "expired", "revoked"] = (
        "revoked" if link.revoked_at else "expired" if link.expires_at <= now else "active"
    )
    return TrackingLinkOut(
        id=link.id,
        shipment_id=link.shipment_id,
        label=link.label,
        allowed_fields=list(link.allowed_fields),
        expires_at=link.expires_at,
        revoked_at=link.revoked_at,
        state=state,
        created_at=link.created_at,
    )


def _shipment_for(ctx: RequestContext, shipment_id: uuid.UUID) -> Shipment:
    if ctx.scope != Scope.TENANT:
        raise not_found()
    s: Shipment | None = Shipment.objects.filter(id=shipment_id).first()
    if s is None:
        raise not_found()
    return s


def create_link(ctx: RequestContext, shipment_id: uuid.UUID, data: TrackingLinkIn) -> TrackingLinkCreated:
    s = _shipment_for(ctx, shipment_id)
    fields = sorted(set(data.allowed_fields or DEFAULT_FIELDS))
    token = secrets.token_urlsafe(32)
    link = TrackingLink.for_context(
        shipment=s,
        token_hash=token_hash(token),
        label=data.label,
        allowed_fields=fields,
        expires_at=timezone.now() + timedelta(days=min(data.expires_in_days, MAX_DAYS)),
        created_by=ctx.user_id,
    )
    link.save()
    audit.record(
        "tracking_link.created",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        target_type="tracking_link",
        target_id=str(link.id),
        metadata={"shipment_id": str(s.id), "fields": fields, "expires_at": link.expires_at.isoformat()},
    )
    return TrackingLinkCreated(**_out(link).model_dump(), token=token)


def list_links(ctx: RequestContext, shipment_id: uuid.UUID) -> list[TrackingLinkOut]:
    _shipment_for(ctx, shipment_id)
    return [_out(x) for x in TrackingLink.objects.filter(shipment_id=shipment_id).order_by("-created_at")]


def revoke_link(ctx: RequestContext, link_id: uuid.UUID, reason: str) -> TrackingLinkOut:
    if ctx.scope != Scope.TENANT:
        raise not_found()
    link = lock(TrackingLink.objects.all(), link_id)
    if link.revoked_at is None:
        link.revoked_at, link.revoked_by, link.revoke_reason = (
            timezone.now(),
            ctx.user_id,
            require_reason(reason),
        )
        link.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
        audit.record(
            "tracking_link.revoked",
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            target_type="tracking_link",
            target_id=str(link.id),
            metadata={"reason": link.revoke_reason},
        )
    return _out(link)


# --------------------------------------------------------------------------- public resolution


def resolve_public(token: str) -> PublicTracking:
    """Look up a token without any tenant context, then build the allowlisted view."""
    if not (20 <= len(token) <= 128):
        raise not_found()
    with connection.cursor() as cur:
        cur.execute(
            "SELECT tenant_id, shipment_id, allowed_fields FROM public_resolve_tracking_link(%s)",
            [token_hash(token)],
        )
        row = cur.fetchone()
    if row is None:
        raise not_found()  # unknown, expired or revoked: same answer
    tenant_id, shipment_id, allowed = row
    if isinstance(allowed, str):  # Django loads jsonb from raw cursors as text
        allowed = json.loads(allowed)
    apply_context(tenant_id=tenant_id)  # the rest of this request reads only that tenant's rows
    s = Shipment.objects.filter(id=shipment_id).first()
    if s is None:
        raise not_found()
    return _public_view(s, set(allowed or []))


def _public_view(s: Shipment, allowed: set[str]) -> PublicTracking:
    out: dict[str, Any] = {"reference": s.reference}
    if "status" in allowed:
        out["status"] = s.status
        out["is_delayed"] = s.is_delayed
    if "route" in allowed:
        out["origin_label"], out["destination_label"] = s.origin_label, s.destination_label
    if "eta" in allowed and s.status in MOVING:
        out["eta"], out["eta_method"] = s.eta, s.eta_method or None
    if "delivery" in allowed and s.status == ShipmentStatus.DELIVERED:
        out["delivered_at"] = s.delivered_at
    if "timeline" in allowed:
        out["timeline"] = [
            PublicTimelineItem(label=PUBLIC_EVENTS[e.type], at=e.occurred_at)
            for e in ShipmentEvent.objects.filter(shipment_id=s.id, type__in=PUBLIC_EVENTS).order_by("id")
        ]
    if "position" in allowed and s.status in MOVING:
        out["position"] = _coarse_position(s.id)
    return PublicTracking(**out)


def _coarse_position(shipment_id: uuid.UUID) -> PublicPosition | None:
    from corridor.tracking import services as tracking
    from corridor.trips import services as trips

    moving = trips.moving_trip_for_shipment(shipment_id)
    if moving is None:
        return None
    point = tracking.latest_point(moving[1], trip_id=moving[0])
    if point is None:
        return None

    def r(x: float) -> float:
        return round(round(x / COARSE_DEGREES) * COARSE_DEGREES, 4)

    return PublicPosition(
        latitude=r(point.latitude),
        longitude=r(point.longitude),
        recorded_at=point.recorded_at,
        received_at=point.received_at,
        freshness=point.freshness,
        precision_km=1.0,
    )


def position_for(ctx: RequestContext, shipment_id: uuid.UUID) -> PublicPosition | None:
    """Approximate position of a shipment the caller may see (customer portal, office), only while it
    is on the road. Same rounding and rules as the public tracking page."""
    from corridor.shipments import services as shipments

    s = shipments.visible(ctx).filter(id=shipment_id).first()
    if s is None:
        raise not_found()
    return _coarse_position(s.id) if s.status in MOVING else None


def lookup_public(container_number: str, reference: str) -> PublicTracking:
    """Public "track a container": container number AND shipment reference must both match one
    shipment (D-075). Same allowlisted view as a tracking link with all public fields; any mismatch,
    ambiguity or inactive company answers the same 404."""
    from corridor.shipments.services import normalize_container_number

    number = normalize_container_number(container_number)
    ref = "".join(reference.split()).upper()[:40]
    if not (11 <= len(number) <= 13) or not (3 <= len(ref) <= 40):
        raise not_found()
    with connection.cursor() as cur:
        cur.execute("SELECT tenant_id, shipment_id FROM public_find_shipment(%s, %s)", [number, ref])
        rows = cur.fetchall()
    if len(rows) != 1:
        raise not_found()
    tenant_id, shipment_id = rows[0]
    apply_context(tenant_id=tenant_id)
    s = Shipment.objects.filter(id=shipment_id).first()
    if s is None:
        raise not_found()
    return _public_view(s, set(DEFAULT_FIELDS))
