"""trips Ninja router."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.trips import services
from corridor.trips.schemas import (
    ActionIn,
    AssignIn,
    ReasonIn,
    TripCorrectionIn,
    TripEventOut,
    TripIn,
    TripOut,
    TripPage,
)

router = Router(tags=["trips"], auth=tenant_auth)


@router.get("/trips", response=TripPage, summary="List trips (drivers: their own)")
@requires("shipments.read")
def list_trips(
    request: HttpRequest, status: str | None = None, cursor: str | None = None, limit: int | None = None
) -> TripPage:
    return services.list_trips(ctx_of(request), status=status, cursor=cursor, limit=limit)


@router.post("/trips", response={201: TripOut}, summary="Plan a trip for shipments")
@requires("trips.assign")
@idempotent
def create_trip(request: HttpRequest, payload: TripIn) -> Status[TripOut]:
    return Status(201, services.create_trip(ctx_of(request), payload))


@router.get("/trips/{trip_id}", response=TripOut, summary="A trip")
@requires("shipments.read")
def get_trip(request: HttpRequest, trip_id: uuid.UUID) -> TripOut:
    return services.get_trip(ctx_of(request), trip_id)


@router.get("/trips/{trip_id}/events", response=list[TripEventOut], summary="Trip history")
@requires("shipments.read")
def list_events(request: HttpRequest, trip_id: uuid.UUID) -> list[TripEventOut]:
    return services.list_events(ctx_of(request), trip_id)


@router.post("/trips/{trip_id}/assign", response=TripOut, summary="Assign vehicle, driver (and trailer)")
@requires("trips.assign")
@idempotent
def assign(request: HttpRequest, trip_id: uuid.UUID, payload: AssignIn) -> TripOut:
    return services.assign_trip(ctx_of(request), trip_id, payload)


@router.post("/trips/{trip_id}/unassign", response=TripOut, summary="Release the assignment")
@requires("trips.assign")
@idempotent
def unassign(request: HttpRequest, trip_id: uuid.UUID, payload: ReasonIn) -> TripOut:
    return services.unassign_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/cancel", response=TripOut, summary="Cancel a planned or assigned trip")
@requires("trips.assign")
@idempotent
def cancel(request: HttpRequest, trip_id: uuid.UUID, payload: ReasonIn) -> TripOut:
    return services.cancel_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/start", response=TripOut, summary="Start the trip (assigned driver)")
@requires("trips.start")
@idempotent
def start(request: HttpRequest, trip_id: uuid.UUID, payload: ActionIn) -> TripOut:
    return services.start_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/pause", response=TripOut, summary="Pause")
@requires("trips.pause")
@idempotent
def pause(request: HttpRequest, trip_id: uuid.UUID, payload: ActionIn) -> TripOut:
    return services.pause_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/resume", response=TripOut, summary="Resume")
@requires("trips.pause")
@idempotent
def resume(request: HttpRequest, trip_id: uuid.UUID, payload: ActionIn) -> TripOut:
    return services.resume_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/complete", response=TripOut, summary="Complete the trip")
@requires("trips.complete")
@idempotent
def complete(request: HttpRequest, trip_id: uuid.UUID, payload: ActionIn) -> TripOut:
    return services.complete_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/abort", response=TripOut, summary="Abort a running trip (reason required)")
@requires("trips.act_on_behalf")
@idempotent
def abort(request: HttpRequest, trip_id: uuid.UUID, payload: ReasonIn) -> TripOut:
    return services.abort_trip(ctx_of(request), trip_id, payload.reason)


@router.post("/trips/{trip_id}/corrections", response=TripOut, summary="Correct the status (reason required)")
@requires("trips.correct")
@idempotent
def correct(request: HttpRequest, trip_id: uuid.UUID, payload: TripCorrectionIn) -> TripOut:
    return services.correct_trip(ctx_of(request), trip_id, payload)
