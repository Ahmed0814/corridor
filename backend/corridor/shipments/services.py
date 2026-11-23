"""shipments public interface and lifecycle (MASTER_PROMPT §4.3, state-machines.md "Shipment").

    draft --confirm--> confirmed --dispatch--> dispatched --(trip started)--> in_transit
    in_transit --border arrival--> at_border --clearance (authorized only)--> in_transit
    in_transit --deliver--> delivered
    in_transit --fail--> delivery_failed --reattempt--> in_transit
    draft|confirmed --cancel--> cancelled             ("delayed" is a flag, not a state)

GPS arrival at a border never clears customs (hard rule 8): clearance is a separate, permissioned action.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from django.contrib.gis.geos import Point
from django.db import IntegrityError, transaction
from django.utils import timezone

from corridor.containers import services as containers
from corridor.core.api import ApiError
from corridor.core.lifecycle import ActorKind, assert_state, lock, not_found, require_reason, rule
from corridor.core.pagination import paginate
from corridor.customers import services as customers
from corridor.events import services as events
from corridor.identity.schemas import RequestContext, Scope
from corridor.shipments.models import Shipment, ShipmentContainer, ShipmentEvent, ShipmentStatus
from corridor.shipments.schemas import (
    BorderIn,
    ContainerRef,
    CorrectionIn,
    DeliverIn,
    GeoPoint,
    ShipmentEventOut,
    ShipmentIn,
    ShipmentOut,
    ShipmentPage,
    ShipmentUpdateIn,
)

S = ShipmentStatus


def _trips() -> Any:
    from corridor.trips import services as trips  # lazy: trips depends on shipments

    return trips


# ---------------------------------------------------------------- visibility (scope rules)


def visible(ctx: RequestContext) -> Any:
    """Shipments this caller may see: tenant roles all, customers their own, drivers their trips'."""
    qs = Shipment.objects.all()
    if ctx.scope == Scope.TENANT:
        return qs
    if ctx.scope == Scope.CUSTOMER:
        return qs.filter(customer_id=ctx.customer_id) if ctx.customer_id else qs.none()
    if ctx.scope == Scope.DRIVER:
        return (
            qs.filter(id__in=_trips().shipment_ids_for_driver(ctx.driver_id)) if ctx.driver_id else qs.none()
        )
    return qs.none()


def _get_visible_for_update(ctx: RequestContext, shipment_id: uuid.UUID) -> Shipment:
    shipment: Shipment = lock(visible(ctx), shipment_id)
    return shipment


# ---------------------------------------------------------------- output


def _pt(p: Point | None) -> GeoPoint | None:
    return GeoPoint(lat=p.y, lng=p.x) if p is not None else None


def _to_point(g: GeoPoint | None) -> Point | None:
    return Point(g.lng, g.lat, srid=4326) if g is not None else None


def _active_container_ids(shipment_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        ShipmentContainer.objects.filter(shipment_id=shipment_id, released_at__isnull=True).values_list(
            "container_id", flat=True
        )
    )


def _out(s: Shipment, *, customer_names: dict[uuid.UUID, str] | None = None) -> ShipmentOut:
    links = list(ShipmentContainer.objects.filter(shipment_id=s.id).order_by("id"))
    nums = containers.numbers([link.container_id for link in links])
    names = customer_names if customer_names is not None else customers.names([s.customer_id])
    return ShipmentOut(
        id=s.id,
        reference=s.reference,
        customer_id=s.customer_id,
        customer_name=names.get(s.customer_id),
        status=s.status,
        is_delayed=s.is_delayed,
        delay_reason=s.delay_reason,
        cargo_description=s.cargo_description,
        weight_kg=s.weight_grams / 1000 if s.weight_grams is not None else None,
        dimensions=s.dimensions,
        origin_label=s.origin_label,
        origin=_pt(s.origin_point),
        destination_label=s.destination_label,
        destination=_pt(s.destination_point),
        eta=s.eta,
        eta_method=s.eta_method,
        eta_remaining_km=s.eta_remaining_km,
        eta_basis_recorded_at=s.eta_basis_recorded_at,
        delivered_at=s.delivered_at,
        recipient_name=s.recipient_name,
        containers=[
            ContainerRef(id=link.container_id, number=nums.get(link.container_id, "")) for link in links
        ],
        trip_ids=_trips().trip_ids_for_shipment(s.id),
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


def _event(
    s: Shipment,
    etype: str,
    *,
    from_status: str = "",
    ctx: RequestContext | None,
    reason: str = "",
    payload: dict[str, Any] | None = None,
    actor_kind: ActorKind | None = None,
) -> None:
    ShipmentEvent.for_context(
        shipment=s,
        type=etype,
        from_status=from_status,
        to_status=s.status,
        actor_kind=(actor_kind or (ActorKind.USER if ctx else ActorKind.SYSTEM)).value,
        actor_user_id=ctx.user_id if ctx else None,
        reason=reason,
        payload=payload or {},
    ).save()


def _transition(
    s: Shipment,
    to: str,
    etype: str,
    ctx: RequestContext | None,
    *,
    reason: str = "",
    payload: dict[str, Any] | None = None,
    actor_kind: ActorKind | None = None,
) -> None:
    previous = s.status
    s.status = to
    s.save(
        update_fields=["status", "updated_at", "delivered_at", "recipient_name", "is_delayed", "delay_reason"]
    )
    _event(s, etype, from_status=previous, ctx=ctx, reason=reason, payload=payload, actor_kind=actor_kind)


def _outbox(etype: str, s: Shipment, **extra: Any) -> None:
    events.emit(
        etype,
        aggregate_type="shipment",
        aggregate_id=s.id,
        payload={"shipment_id": str(s.id), "reference": s.reference, "status": s.status, **extra},
    )


# ---------------------------------------------------------------- queries


def list_shipments(
    ctx: RequestContext,
    *,
    status: str | None,
    customer_id: uuid.UUID | None,
    q: str | None,
    cursor: str | None,
    limit: int | None,
) -> ShipmentPage:
    qs = visible(ctx)
    if status:
        qs = qs.filter(status=status)
    if customer_id:
        qs = qs.filter(customer_id=customer_id)
    if q:
        qs = qs.filter(reference__icontains=q)
    rows, nxt = paginate(qs, cursor, limit)
    names = customers.names(list({r.customer_id for r in rows}))
    return ShipmentPage(items=[_out(r, customer_names=names) for r in rows], next_cursor=nxt)


def get_shipment(ctx: RequestContext, shipment_id: uuid.UUID) -> ShipmentOut:
    s = visible(ctx).filter(id=shipment_id).first()
    if s is None:
        raise not_found()
    return _out(s)


def list_events(ctx: RequestContext, shipment_id: uuid.UUID) -> list[ShipmentEventOut]:
    if not visible(ctx).filter(id=shipment_id).exists():
        raise not_found()
    return [
        ShipmentEventOut.model_validate(e, from_attributes=True)
        for e in ShipmentEvent.objects.filter(shipment_id=shipment_id).order_by("id")
    ]


# ---------------------------------------------------------------- create / edit (draft only)


def _new_reference() -> str:
    return f"SHP-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def _set_containers(s: Shipment, container_ids: list[uuid.UUID]) -> None:
    """Draft containers are linked but not reserved; reservation happens on confirmation."""
    container_ids = list(dict.fromkeys(container_ids))
    if container_ids and len(containers.numbers(container_ids)) != len(container_ids):
        raise not_found("One or more containers were not found.")
    ShipmentContainer.objects.filter(shipment_id=s.id).exclude(container_id__in=container_ids).delete()
    existing = set(ShipmentContainer.objects.filter(shipment_id=s.id).values_list("container_id", flat=True))
    for cid in container_ids:
        if cid not in existing:
            ShipmentContainer.for_context(shipment=s, container_id=cid).save()


def create_shipment(ctx: RequestContext, data: ShipmentIn) -> ShipmentOut:
    if ctx.scope != Scope.TENANT:
        raise not_found()
    rule(
        customers.is_active_customer(data.customer_id),
        "customer_invalid",
        "The customer does not exist or is inactive.",
    )
    reference = data.reference or _new_reference()
    if Shipment.objects.filter(reference=reference).exists():
        raise ApiError(409, "conflict", "A shipment with this reference already exists.")
    s = Shipment.for_context(
        reference=reference,
        customer_id=data.customer_id,
        cargo_description=data.cargo_description,
        weight_grams=round(data.weight_kg * 1000) if data.weight_kg is not None else None,
        dimensions=data.dimensions,
        origin_label=data.origin_label,
        origin_point=_to_point(data.origin),
        destination_label=data.destination_label,
        destination_point=_to_point(data.destination),
        created_by=ctx.user_id,
    )
    try:
        with transaction.atomic():
            s.save()
            _set_containers(s, data.container_ids)
    except IntegrityError as exc:
        raise ApiError(
            409, "container_unavailable", "A container is already on another active shipment."
        ) from exc
    _event(s, "created", ctx=ctx)
    _outbox("shipment.created", s, customer_id=str(s.customer_id))
    return _out(s)


def update_shipment(ctx: RequestContext, shipment_id: uuid.UUID, data: ShipmentUpdateIn) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.DRAFT,), "edit")
    fields = data.model_dump(exclude_unset=True)
    if "weight_kg" in fields:
        w = fields.pop("weight_kg")
        s.weight_grams = round(w * 1000) if w is not None else None
    if "origin" in fields:
        fields.pop("origin")
        s.origin_point = _to_point(data.origin)
    if "destination" in fields:
        fields.pop("destination")
        s.destination_point = _to_point(data.destination)
    container_ids = fields.pop("container_ids", None)
    for field, value in fields.items():
        if value is not None:
            setattr(s, field, value)
    s.save()
    if container_ids is not None:
        _set_containers(s, container_ids)
    _event(
        s,
        "updated",
        from_status=s.status,
        ctx=ctx,
        payload={"fields": sorted(data.model_dump(exclude_unset=True))},
    )
    return _out(s)


# ---------------------------------------------------------------- transitions


def confirm_shipment(ctx: RequestContext, shipment_id: uuid.UUID) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.DRAFT,), "confirm")
    rule(customers.is_active_customer(s.customer_id), "customer_invalid", "The customer is inactive.")
    containers.reserve(_active_container_ids(s.id), actor_user_id=ctx.user_id, shipment_ref=s.reference)
    _transition(s, S.CONFIRMED, "confirmed", ctx)
    _outbox("shipment.confirmed", s)
    return _out(s)


def cancel_shipment(ctx: RequestContext, shipment_id: uuid.UUID, reason: str) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.DRAFT, S.CONFIRMED), "cancel")
    rule(
        not _trips().has_open_trip(s.id),
        "shipment_on_open_trip",
        "Remove the shipment from its open trips first.",
    )
    if s.status == S.CONFIRMED:
        _release_containers(s, ctx)
    _transition(s, S.CANCELLED, "cancelled", ctx, reason=require_reason(reason))
    return _out(s)


def dispatch_shipment(ctx: RequestContext, shipment_id: uuid.UUID) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.CONFIRMED,), "dispatch")
    trip_id = _trips().assigned_trip_for_shipment(s.id)
    rule(
        trip_id is not None,
        "no_assigned_trip",
        "Dispatch needs a trip for this shipment with a vehicle and a driver assigned.",
    )
    _transition(s, S.DISPATCHED, "dispatched", ctx, payload={"trip_id": str(trip_id)})
    _outbox("shipment.dispatched", s, trip_id=str(trip_id))
    return _out(s)


def mark_in_transit_for_trip(ctx: RequestContext, shipment_ids: list[uuid.UUID], trip_id: uuid.UUID) -> None:
    """System transition when a trip starts: dispatched -> in_transit (later legs: already moving)."""
    for s in Shipment.objects.select_for_update().filter(id__in=shipment_ids).order_by("id"):
        if s.status == S.DISPATCHED:
            _transition(
                s,
                S.IN_TRANSIT,
                "in_transit",
                ctx,
                payload={"trip_id": str(trip_id)},
                actor_kind=ActorKind.SYSTEM,
            )


def assert_startable(shipment_ids: list[uuid.UUID]) -> None:
    """A trip may start only when every shipment on it is dispatched or already moving."""
    bad = list(
        Shipment.objects.filter(id__in=shipment_ids)
        .exclude(status__in=[S.DISPATCHED, S.IN_TRANSIT, S.AT_BORDER, S.DELIVERY_FAILED])
        .values_list("reference", "status")
    )
    rule(
        not bad,
        "shipments_not_dispatched",
        "Every shipment on the trip must be dispatched before it starts.",
        {"shipments": [{"reference": r, "status": st} for r, st in bad]},
    )


def assert_attachable(shipment_ids: list[uuid.UUID]) -> None:
    """Shipments that can be planned onto a trip: confirmed, or moving (multi-leg)."""
    found = dict(Shipment.objects.filter(id__in=shipment_ids).values_list("id", "status"))
    if len(found) != len(set(shipment_ids)):
        raise not_found("One or more shipments were not found.")
    bad = {
        str(k): v
        for k, v in found.items()
        if v not in (S.CONFIRMED, S.DISPATCHED, S.IN_TRANSIT, S.DELIVERY_FAILED)
    }
    rule(
        not bad,
        "shipment_not_plannable",
        "Only confirmed or moving shipments can be put on a trip.",
        {"shipments": bad},
    )


def record_border_arrival(ctx: RequestContext, shipment_id: uuid.UUID, data: BorderIn) -> ShipmentOut:
    """Arrival at a border (operator, or later a verified geofence). NOT customs clearance."""
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.IN_TRANSIT,), "record border arrival")
    _transition(s, S.AT_BORDER, "border_arrived", ctx, payload={"border": data.border, "note": data.note})
    _outbox("border.arrived", s, border=data.border)
    return _out(s)


def confirm_border_clearance(ctx: RequestContext, shipment_id: uuid.UUID, data: BorderIn) -> ShipmentOut:
    """Customs/border clearance, by an authorized operator only (hard rule 8)."""
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.AT_BORDER,), "confirm border clearance")
    _transition(s, S.IN_TRANSIT, "border_cleared", ctx, payload={"border": data.border, "note": data.note})
    _outbox("border.clearance.confirmed", s, border=data.border, confirmed_by=str(ctx.user_id))
    return _out(s)


def deliver_shipment(ctx: RequestContext, shipment_id: uuid.UUID, data: DeliverIn) -> ShipmentOut:
    """in_transit -> delivered. Premature delivery is impossible: draft/confirmed/dispatched/at_border
    are rejected. Needs proof of delivery: delivery photo(s) and a signature of THIS shipment; they
    become visible to the customer once the delivery is confirmed."""
    from corridor.documents import services as documents

    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.IN_TRANSIT,), "deliver")
    rule(_trips().has_started_trip(s.id), "no_started_trip", "The shipment has no started trip.")
    photo_ids = list(dict.fromkeys(data.photo_ids))
    documents.assert_evidence(s.id, photo_ids=photo_ids, signature_id=data.signature_id)
    documents.share_with_customer([*photo_ids, data.signature_id])
    s.delivered_at = timezone.now()
    s.recipient_name = data.recipient_name
    _release_containers(s, ctx)
    _transition(
        s,
        S.DELIVERED,
        "delivered",
        ctx,
        payload={
            "recipient_name": data.recipient_name,
            "note": data.note,
            "photo_ids": [str(p) for p in photo_ids],
            "signature_id": str(data.signature_id),
        },
    )
    _outbox("shipment.delivered", s, delivered_at=s.delivered_at.isoformat())
    return _out(s)


def record_failed_delivery(ctx: RequestContext, shipment_id: uuid.UUID, reason: str) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.IN_TRANSIT,), "record a failed delivery")
    _transition(s, S.DELIVERY_FAILED, "delivery_failed", ctx, reason=require_reason(reason))
    return _out(s)


def reattempt_delivery(ctx: RequestContext, shipment_id: uuid.UUID) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(s.status, (S.DELIVERY_FAILED,), "reattempt delivery")
    _transition(s, S.IN_TRANSIT, "delivery_reattempt", ctx)
    return _out(s)


def mark_delayed(ctx: RequestContext, shipment_id: uuid.UUID, reason: str) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    assert_state(
        s.status, (S.CONFIRMED, S.DISPATCHED, S.IN_TRANSIT, S.AT_BORDER, S.DELIVERY_FAILED), "mark delayed"
    )
    s.is_delayed, s.delay_reason = True, require_reason(reason)
    s.save(update_fields=["is_delayed", "delay_reason", "updated_at"])
    _event(s, "delayed", from_status=s.status, ctx=ctx, reason=s.delay_reason)
    _outbox("shipment.delayed", s, reason=s.delay_reason)
    return _out(s)


def clear_delay(ctx: RequestContext, shipment_id: uuid.UUID) -> ShipmentOut:
    s = _get_visible_for_update(ctx, shipment_id)
    rule(s.is_delayed, "not_delayed", "The shipment is not marked delayed.")
    s.is_delayed, s.delay_reason = False, ""
    s.save(update_fields=["is_delayed", "delay_reason", "updated_at"])
    _event(s, "delay_cleared", from_status=s.status, ctx=ctx)
    return _out(s)


def correct_status(ctx: RequestContext, shipment_id: uuid.UUID, data: CorrectionIn) -> ShipmentOut:
    """Authorized correction (e.g. reopening a delivered shipment). Recorded as a new event with the
    actor and a required reason; earlier events are never changed (hard rule 5)."""
    s = _get_visible_for_update(ctx, shipment_id)
    rule(data.to_status != s.status, "no_change", "The shipment already has that status.")
    if s.status == S.DELIVERED and data.to_status != S.DELIVERED:
        s.delivered_at = None
    _transition(
        s,
        data.to_status,
        "correction",
        ctx,
        reason=require_reason(data.reason),
        payload={"corrected_from": s.status},
    )
    return _out(s)


def _release_containers(s: Shipment, ctx: RequestContext | None) -> None:
    ids = _active_container_ids(s.id)
    containers.release(ids, actor_user_id=ctx.user_id if ctx else None, shipment_ref=s.reference)
    ShipmentContainer.objects.filter(shipment_id=s.id, released_at__isnull=True).update(
        released_at=timezone.now()
    )


# ---------------------------------------------------------------- used by trips


def statuses(shipment_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Shipment.objects.filter(id__in=shipment_ids).values_list("id", "status"))


def references(shipment_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Shipment.objects.filter(id__in=shipment_ids).values_list("id", "reference"))


# ---------------------------------------------------------------- GPS-driven updates (Phase 6)


def border_arrival_from_geofence(
    shipment_ids: list[uuid.UUID],
    *,
    border: str,
    trip_id: uuid.UUID,
    checkpoint_id: uuid.UUID,
    gps_event_id: uuid.UUID,
    recorded_at: Any,
) -> int:
    """System transition in_transit -> at_border when a trip enters a VERIFIED border checkpoint.
    Arrival only: clearance remains confirm_border_clearance by an authorized operator (hard rule 8)."""
    moved = 0
    for s in (
        Shipment.objects.select_for_update().filter(id__in=shipment_ids, status=S.IN_TRANSIT).order_by("id")
    ):
        payload = {
            "border": border,
            "source": "geofence",
            "trip_id": str(trip_id),
            "checkpoint_id": str(checkpoint_id),
            "gps_event_id": str(gps_event_id),
            "recorded_at": recorded_at.isoformat(),
        }
        _transition(s, S.AT_BORDER, "border_arrived", None, payload=payload, actor_kind=ActorKind.SYSTEM)
        _outbox("border.arrived", s, border=border, source="geofence", trip_id=str(trip_id))
        moved += 1
    return moved


# Deterministic ETA (D-068). An explainable formula, never a model (hard rule 9):
#   remaining = great-circle distance(latest trusted point, destination) x ROAD_FACTOR
#   eta       = point recorded time + remaining / PLANNING_SPEED (+ BORDER_DWELL while at a border)
ETA_METHOD = "deterministic_v1"
ROAD_FACTOR = 1.3  # corridor roads are longer than the straight line
PLANNING_SPEED_KMH = 45.0  # loaded trucks incl. short stops, Djibouti-Addis corridor
BORDER_DWELL_H = 6.0  # typical wait at Galafi/Dewele until clearance
ARRIVED_KM = 2.0  # within this distance the remaining time is zero


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def compute_eta(
    *, lat: float, lng: float, recorded_at: Any, dest_lat: float, dest_lng: float, at_border: bool
) -> tuple[Any, float]:
    """Pure function: (eta, remaining_km). Unit-tested."""
    from datetime import timedelta

    remaining = _haversine_km(lat, lng, dest_lat, dest_lng) * ROAD_FACTOR
    if remaining <= ARRIVED_KM:
        remaining = 0.0
    hours = remaining / PLANNING_SPEED_KMH + (BORDER_DWELL_H if at_border else 0.0)
    return recorded_at + timedelta(hours=hours), round(remaining, 1)


def recompute_eta_for_trip(trip_id: uuid.UUID, *, lat: float, lng: float, recorded_at: Any) -> int:
    """Called by GPS ingestion after a newer trusted point for the trip's vehicle. Shipments without a
    destination point get no ETA (never a guessed one)."""
    updated = 0
    ids = _trips().shipment_ids_for_trip(trip_id)
    for s in Shipment.objects.select_for_update().filter(
        id__in=ids, status__in=[S.DISPATCHED, S.IN_TRANSIT, S.AT_BORDER, S.DELIVERY_FAILED]
    ):
        if s.destination_point is None:
            if s.eta_method != "unavailable_no_destination":
                s.eta, s.eta_method, s.eta_remaining_km = None, "unavailable_no_destination", None
                s.save(update_fields=["eta", "eta_method", "eta_remaining_km", "updated_at"])
            continue
        if s.eta_basis_recorded_at is not None and recorded_at <= s.eta_basis_recorded_at:
            continue  # never let an older point move the ETA (same rule as the latest location)
        eta, remaining = compute_eta(
            lat=lat,
            lng=lng,
            recorded_at=recorded_at,
            dest_lat=s.destination_point.y,
            dest_lng=s.destination_point.x,
            at_border=s.status == S.AT_BORDER,
        )
        s.eta, s.eta_method, s.eta_remaining_km = eta, ETA_METHOD, remaining
        s.eta_computed_at, s.eta_basis_recorded_at = timezone.now(), recorded_at
        s.save(
            update_fields=[
                "eta",
                "eta_method",
                "eta_remaining_km",
                "eta_computed_at",
                "eta_basis_recorded_at",
                "updated_at",
            ]
        )
        updated += 1
    return updated


def customer_id_of(shipment_id: uuid.UUID) -> uuid.UUID | None:
    return Shipment.objects.filter(id=shipment_id).values_list("customer_id", flat=True).first()


def normalize_container_number(raw: str) -> str:
    return "".join(raw.split()).upper()[:13]


def find_by_container(ctx: RequestContext, number: str) -> list[ShipmentOut]:
    """Shipments that carry (or carried) this container, newest first. Scope rules apply:
    office users see the company's shipments, customers only their own, drivers their trips'."""
    n = normalize_container_number(number)
    if len(n) < 4:
        return []
    rows = list(
        visible(ctx).filter(container_links__container__number=n).distinct().order_by("-created_at")[:20]
    )
    names = customers.names(list({r.customer_id for r in rows}))
    return [_out(r, customer_names=names) for r in rows]
