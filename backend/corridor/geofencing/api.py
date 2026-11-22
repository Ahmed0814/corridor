"""geofencing Ninja router: geofences, checkpoints, checkpoint visits of a trip."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.geofencing import services
from corridor.geofencing.schemas import (
    CheckpointIn,
    CheckpointOut,
    CheckpointVisitOut,
    GeofenceIn,
    GeofenceOut,
)
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["geofencing"], auth=tenant_auth)


@router.get("/geofences", response=list[GeofenceOut], summary="Geofences of the company")
@requires("tracking.read")
def list_geofences(request: HttpRequest) -> list[GeofenceOut]:
    return services.list_geofences(ctx_of(request))


@router.post("/geofences", response={201: GeofenceOut}, summary="Draw a geofence (starts unverified)")
@requires("geofences.write")
@idempotent
def create_geofence(request: HttpRequest, payload: GeofenceIn) -> Status[GeofenceOut]:
    return Status(201, services.create_geofence(ctx_of(request), payload))


@router.post(
    "/geofences/{geofence_id}/verify",
    response=GeofenceOut,
    summary="Confirm the outline matches the real place (needed before border events change statuses)",
)
@requires("geofences.write")
@idempotent
def verify_geofence(request: HttpRequest, geofence_id: uuid.UUID) -> GeofenceOut:
    return services.verify_geofence(ctx_of(request), geofence_id)


@router.post("/geofences/{geofence_id}/deactivate", response=GeofenceOut, summary="Stop using a geofence")
@requires("geofences.write")
@idempotent
def deactivate_geofence(request: HttpRequest, geofence_id: uuid.UUID) -> GeofenceOut:
    return services.set_geofence_active(ctx_of(request), geofence_id, active=False)


@router.post("/geofences/{geofence_id}/activate", response=GeofenceOut, summary="Use a geofence again")
@requires("geofences.write")
@idempotent
def activate_geofence(request: HttpRequest, geofence_id: uuid.UUID) -> GeofenceOut:
    return services.set_geofence_active(ctx_of(request), geofence_id, active=True)


@router.get("/checkpoints", response=list[CheckpointOut], summary="Checkpoints watched on every trip")
@requires("tracking.read")
def list_checkpoints(request: HttpRequest) -> list[CheckpointOut]:
    return services.list_checkpoints(ctx_of(request))


@router.post("/checkpoints", response={201: CheckpointOut}, summary="Watch a geofence as a checkpoint")
@requires("geofences.write")
@idempotent
def create_checkpoint(request: HttpRequest, payload: CheckpointIn) -> Status[CheckpointOut]:
    return Status(201, services.create_checkpoint(ctx_of(request), payload))


@router.post("/checkpoints/{checkpoint_id}/deactivate", response=CheckpointOut, summary="Stop watching")
@requires("geofences.write")
@idempotent
def deactivate_checkpoint(request: HttpRequest, checkpoint_id: uuid.UUID) -> CheckpointOut:
    return services.set_checkpoint_active(ctx_of(request), checkpoint_id, active=False)


@router.get(
    "/trips/{trip_id}/checkpoint-visits",
    response=list[CheckpointVisitOut],
    summary="Checkpoints this trip entered and left (from trusted GPS)",
)
@requires("tracking.read")
def trip_visits(request: HttpRequest, trip_id: uuid.UUID) -> list[CheckpointVisitOut]:
    return services.trip_visits(ctx_of(request), trip_id)
