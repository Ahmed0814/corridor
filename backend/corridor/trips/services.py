"""trips public interface and lifecycle (MASTER_PROMPT §4.3, state-machines.md "Trip").

    planned --assign--> assigned --start--> in_progress <--pause/resume--> paused
    in_progress|paused --complete--> completed      in_progress|paused --abort (reason)--> aborted
    planned|assigned --cancel--> cancelled          assigned --unassign--> planned

Only the assigned driver starts/pauses/completes their trip; an office user may act on their behalf
with ``trips.act_on_behalf`` and a reason. Conflicting assignments are stopped by partial unique
indexes, so a concurrent race has exactly one winner (409 ``assignment_conflict`` for the other).
Starting a trip opens its GPS tracking session; completing or aborting closes it (Phase 4).
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from corridor.core.api import ApiError
from corridor.core.lifecycle import ActorKind, assert_state, lock, not_found, require_reason, rule
from corridor.core.pagination import paginate
from corridor.drivers import services as drivers
from corridor.events import services as events
from corridor.fleet import services as fleet
from corridor.identity.schemas import RequestContext, Scope
from corridor.shipments import services as shipments
from corridor.tracking import services as tracking
from corridor.trips.models import OPEN_STATUSES, Trip, TripAssignment, TripEvent, TripShipment, TripStatus
from corridor.trips.schemas import (
    AssignIn,
    AssignmentOut,
    DispatchPlanIn,
    TripCorrectionIn,
    TripEventOut,
    TripIn,
    TripOut,
    TripPage,
)

T = TripStatus
ACTIVE = TripAssignment.Status.ACTIVE


# ---------------------------------------------------------------- visibility


def _visible(ctx: RequestContext) -> Any:
    """Tenant roles see all trips; drivers only trips they were assigned to; customers none."""
    qs = Trip.objects.all()
    if ctx.scope == Scope.TENANT:
        return qs
    if ctx.scope == Scope.DRIVER and ctx.driver_id:
        return qs.filter(id__in=TripAssignment.objects.filter(driver_id=ctx.driver_id).values("trip_id"))
    return qs.none()


def _active_assignment(trip_id: uuid.UUID) -> TripAssignment | None:
    return TripAssignment.objects.filter(trip_id=trip_id, status=ACTIVE).first()


def _shipment_ids(trip_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        TripShipment.objects.filter(trip_id=trip_id).order_by("id").values_list("shipment_id", flat=True)
    )


def _assignment_out(a: TripAssignment | None) -> AssignmentOut | None:
    if a is None:
        return None
    return AssignmentOut(
        id=a.id,
        vehicle_id=a.vehicle_id,
        vehicle_plate=fleet.plates([a.vehicle_id]).get(a.vehicle_id),
        driver_id=a.driver_id,
        driver_name=drivers.names([a.driver_id]).get(a.driver_id),
        trailer_id=a.trailer_id,
        status=a.status,
        created_at=a.created_at,
        released_at=a.released_at,
    )


def _out(t: Trip) -> TripOut:
    return TripOut(
        id=t.id,
        reference=t.reference,
        status=t.status,
        mode=t.mode,
        origin_label=t.origin_label,
        destination_label=t.destination_label,
        planned_start=t.planned_start,
        started_at=t.started_at,
        completed_at=t.completed_at,
        shipment_ids=_shipment_ids(t.id),
        assignment=_assignment_out(_active_assignment(t.id)),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _event(
    t: Trip,
    etype: str,
    ctx: RequestContext | None,
    *,
    from_status: str = "",
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    TripEvent.for_context(
        trip=t,
        type=etype,
        from_status=from_status,
        to_status=t.status,
        actor_kind=(ActorKind.USER if ctx else ActorKind.SYSTEM).value,
        actor_user_id=ctx.user_id if ctx else None,
        reason=reason,
        payload=payload or {},
    ).save()


def _transition(
    t: Trip,
    to: str,
    etype: str,
    ctx: RequestContext | None,
    *,
    reason: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    previous = t.status
    t.status = to
    t.save(update_fields=["status", "started_at", "completed_at", "updated_at"])
    _event(t, etype, ctx, from_status=previous, reason=reason, payload=payload)


def _outbox(etype: str, t: Trip, **extra: Any) -> None:
    events.emit(
        etype,
        aggregate_type="trip",
        aggregate_id=t.id,
        payload={"trip_id": str(t.id), "reference": t.reference, "status": t.status, **extra},
    )


def _release(t: Trip) -> None:
    TripAssignment.objects.filter(trip_id=t.id, status=ACTIVE).update(
        status=TripAssignment.Status.RELEASED, released_at=timezone.now()
    )


def _authorize_driver_action(ctx: RequestContext, t: Trip, reason: str) -> str:
    """The assigned driver acts directly; an office user needs trips.act_on_behalf + a reason."""
    a = _active_assignment(t.id)
    if ctx.scope == Scope.DRIVER:
        rule(
            a is not None and a.driver_id == ctx.driver_id,
            "not_assigned_driver",
            "Only the driver assigned to this trip can do this.",
        )
        return reason
    if not ctx.has("trips.act_on_behalf"):
        raise ApiError(403, "forbidden", "Acting on behalf of the driver requires trips.act_on_behalf.")
    return require_reason(reason)


# ---------------------------------------------------------------- queries


def list_trips(ctx: RequestContext, *, status: str | None, cursor: str | None, limit: int | None) -> TripPage:
    qs = _visible(ctx)
    if status:
        qs = qs.filter(status=status)
    rows, nxt = paginate(qs, cursor, limit)
    return TripPage(items=[_out(t) for t in rows], next_cursor=nxt)


def get_trip(ctx: RequestContext, trip_id: uuid.UUID) -> TripOut:
    t = _visible(ctx).filter(id=trip_id).first()
    if t is None:
        raise not_found()
    return _out(t)


def list_events(ctx: RequestContext, trip_id: uuid.UUID) -> list[TripEventOut]:
    if not _visible(ctx).filter(id=trip_id).exists():
        raise not_found()
    return [
        TripEventOut.model_validate(e, from_attributes=True)
        for e in TripEvent.objects.filter(trip_id=trip_id).order_by("id")
    ]


# ---------------------------------------------------------------- planning


def _new_reference() -> str:
    return f"TRP-{timezone.now():%y%m%d}-{secrets.token_hex(3).upper()}"


def create_trip(ctx: RequestContext, data: TripIn) -> TripOut:
    if ctx.scope != Scope.TENANT:
        raise not_found()
    shipment_ids = list(dict.fromkeys(data.shipment_ids))
    shipments.assert_attachable(shipment_ids)
    reference = data.reference or _new_reference()
    if Trip.objects.filter(reference=reference).exists():
        raise ApiError(409, "conflict", "A trip with this reference already exists.")
    t = Trip.for_context(
        reference=reference,
        origin_label=data.origin_label,
        destination_label=data.destination_label,
        planned_start=data.planned_start,
        created_by=ctx.user_id,
    )
    t.save()
    for sid in shipment_ids:
        TripShipment.for_context(trip=t, shipment_id=sid).save()
    _event(t, "created", ctx, payload={"shipment_ids": [str(s) for s in shipment_ids]})
    _outbox("trip.created", t, shipment_ids=[str(s) for s in shipment_ids])
    return _out(t)


def assign_trip(ctx: RequestContext, trip_id: uuid.UUID, data: AssignIn) -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.PLANNED,), "assign")
    fleet.assert_vehicle_assignable(data.vehicle_id)
    drivers.assert_driver_assignable(data.driver_id)
    if data.trailer_id:
        fleet.assert_trailer_assignable(data.trailer_id)
    try:
        with transaction.atomic():
            TripAssignment.for_context(
                trip=t,
                vehicle_id=data.vehicle_id,
                driver_id=data.driver_id,
                trailer_id=data.trailer_id,
                assigned_by=ctx.user_id,
            ).save()
    except IntegrityError as exc:
        raise ApiError(
            409, "assignment_conflict", "The vehicle, driver or trailer already has an active assignment."
        ) from exc
    _transition(
        t,
        T.ASSIGNED,
        "assigned",
        ctx,
        payload={"vehicle_id": str(data.vehicle_id), "driver_id": str(data.driver_id)},
    )
    _outbox("trip.assigned", t, vehicle_id=str(data.vehicle_id), driver_id=str(data.driver_id))
    return _out(t)


def unassign_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str) -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.ASSIGNED,), "unassign")
    _release(t)
    _transition(t, T.PLANNED, "unassigned", ctx, reason=require_reason(reason))
    return _out(t)


def cancel_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str) -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.PLANNED, T.ASSIGNED), "cancel")
    _release(t)
    _transition(t, T.CANCELLED, "cancelled", ctx, reason=require_reason(reason))
    return _out(t)


# ---------------------------------------------------------------- execution


def start_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str = "") -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.ASSIGNED,), "start")
    reason = _authorize_driver_action(ctx, t, reason)
    sids = _shipment_ids(t.id)
    shipments.assert_startable(sids)
    t.started_at = timezone.now()
    _transition(t, T.IN_PROGRESS, "started", ctx, reason=reason)
    shipments.mark_in_transit_for_trip(ctx, sids, t.id)
    a = _active_assignment(t.id)
    if a is not None:
        tracking.open_session(t.id, a.driver_id, a.vehicle_id)  # GPS accepted only inside it (D-013)
    _outbox(
        "trip.started",
        t,
        driver_id=str(a.driver_id) if a else None,
        vehicle_id=str(a.vehicle_id) if a else None,
    )
    return _out(t)


def pause_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str = "") -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.IN_PROGRESS,), "pause")
    _transition(t, T.PAUSED, "paused", ctx, reason=_authorize_driver_action(ctx, t, reason))
    tracking.set_session_paused(t.id, True)
    return _out(t)


def resume_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str = "") -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.PAUSED,), "resume")
    _transition(t, T.IN_PROGRESS, "resumed", ctx, reason=_authorize_driver_action(ctx, t, reason))
    tracking.set_session_paused(t.id, False)
    return _out(t)


def complete_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str = "") -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.IN_PROGRESS, T.PAUSED), "complete")
    reason = _authorize_driver_action(ctx, t, reason)
    t.completed_at = timezone.now()
    _release(t)
    _transition(t, T.COMPLETED, "completed", ctx, reason=reason)
    tracking.close_session(t.id)
    _outbox("trip.completed", t)
    return _out(t)


def abort_trip(ctx: RequestContext, trip_id: uuid.UUID, reason: str) -> TripOut:
    t = lock(_visible(ctx), trip_id)
    assert_state(t.status, (T.IN_PROGRESS, T.PAUSED), "abort")
    if ctx.scope != Scope.TENANT:
        raise ApiError(403, "forbidden", "Only office users can abort a trip.")
    t.completed_at = timezone.now()
    _release(t)
    _transition(t, T.ABORTED, "aborted", ctx, reason=require_reason(reason))
    tracking.close_session(t.id)
    return _out(t)


def correct_trip(ctx: RequestContext, trip_id: uuid.UUID, data: TripCorrectionIn) -> TripOut:
    """Authorized correction (e.g. a trip completed by mistake). Recorded as a new event; the
    original events stay. Reopening never re-creates an assignment automatically."""
    t = lock(_visible(ctx), trip_id)
    rule(data.to_status != t.status, "no_change", "The trip already has that status.")
    if data.to_status in (T.IN_PROGRESS, T.PAUSED, T.ASSIGNED):
        rule(
            _active_assignment(t.id) is not None,
            "no_active_assignment",
            "Assign a vehicle and driver before reopening this trip.",
        )
    if data.to_status not in (T.COMPLETED, T.ABORTED):
        t.completed_at = None
    _transition(
        t,
        data.to_status,
        "correction",
        ctx,
        reason=require_reason(data.reason),
        payload={"corrected_from": t.status},
    )
    return _out(t)


# ---------------------------------------------------------------- dispatch orchestration


def plan_and_dispatch(ctx: RequestContext, data: DispatchPlanIn) -> TripOut:
    """Create a trip for confirmed shipments, assign vehicle + driver, and dispatch every shipment,
    in one transaction: all of it happens or none of it does."""
    trip = create_trip(
        ctx,
        TripIn(
            origin_label=data.origin_label,
            destination_label=data.destination_label,
            planned_start=data.planned_start,
            shipment_ids=data.shipment_ids,
        ),
    )
    assign_trip(
        ctx,
        trip.id,
        AssignIn(vehicle_id=data.vehicle_id, driver_id=data.driver_id, trailer_id=data.trailer_id),
    )
    for sid in dict.fromkeys(data.shipment_ids):
        shipments.dispatch_shipment(ctx, sid)
    return get_trip(ctx, trip.id)


# ---------------------------------------------------------------- used by other modules


def trip_ids_for_shipment(shipment_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        TripShipment.objects.filter(shipment_id=shipment_id).order_by("id").values_list("trip_id", flat=True)
    )


def shipment_ids_for_driver(driver_id: uuid.UUID | None) -> list[uuid.UUID]:
    if driver_id is None:
        return []
    trip_ids = TripAssignment.objects.filter(driver_id=driver_id).values("trip_id")
    return list(TripShipment.objects.filter(trip_id__in=trip_ids).values_list("shipment_id", flat=True))


def vehicle_ids_for_driver(driver_id: uuid.UUID | None) -> list[uuid.UUID]:
    if driver_id is None:
        return []
    return list(
        TripAssignment.objects.filter(driver_id=driver_id, status=ACTIVE).values_list("vehicle_id", flat=True)
    )


def active_trip_by_vehicle(vehicle_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    return dict(
        TripAssignment.objects.filter(vehicle_id__in=vehicle_ids, status=ACTIVE).values_list(
            "vehicle_id", "trip_id"
        )
    )


def assigned_trip_for_shipment(shipment_id: uuid.UUID) -> uuid.UUID | None:
    """An open trip carrying this shipment that has an active vehicle + driver assignment."""
    trip_ids = TripShipment.objects.filter(shipment_id=shipment_id).values("trip_id")
    return (
        Trip.objects.filter(
            id__in=trip_ids, status__in=[T.ASSIGNED, T.IN_PROGRESS, T.PAUSED], assignments__status=ACTIVE
        )
        .values_list("id", flat=True)
        .first()
    )


def has_open_trip(shipment_id: uuid.UUID) -> bool:
    trip_ids = TripShipment.objects.filter(shipment_id=shipment_id).values("trip_id")
    return Trip.objects.filter(id__in=trip_ids, status__in=OPEN_STATUSES).exists()


def has_started_trip(shipment_id: uuid.UUID) -> bool:
    trip_ids = TripShipment.objects.filter(shipment_id=shipment_id).values("trip_id")
    return Trip.objects.filter(id__in=trip_ids, status__in=[T.IN_PROGRESS, T.PAUSED, T.COMPLETED]).exists()
