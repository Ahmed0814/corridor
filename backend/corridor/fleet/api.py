"""fleet Ninja router."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.fleet import services
from corridor.fleet.schemas import (
    AssetStatusIn,
    TrailerIn,
    TrailerOut,
    TrailerPage,
    VehicleIn,
    VehicleOut,
    VehiclePage,
    VehicleUpdateIn,
)
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["fleet"], auth=tenant_auth)


@router.get("/vehicles", response=VehiclePage, summary="List vehicles")
@requires("fleet.read")
def list_vehicles(
    request: HttpRequest, status: str | None = None, cursor: str | None = None, limit: int | None = None
) -> VehiclePage:
    return services.list_vehicles(ctx_of(request), status=status, cursor=cursor, limit=limit)


@router.post("/vehicles", response={201: VehicleOut}, summary="Register a vehicle")
@requires("fleet.write")
@idempotent
def create_vehicle(request: HttpRequest, payload: VehicleIn) -> Status[VehicleOut]:
    return Status(201, services.create_vehicle(ctx_of(request), payload))


@router.get("/vehicles/{vehicle_id}", response=VehicleOut, summary="A vehicle")
@requires("fleet.read")
def get_vehicle(request: HttpRequest, vehicle_id: uuid.UUID) -> VehicleOut:
    return services.get_vehicle(ctx_of(request), vehicle_id)


@router.patch("/vehicles/{vehicle_id}", response=VehicleOut, summary="Update vehicle details")
@requires("fleet.write")
@idempotent
def update_vehicle(request: HttpRequest, vehicle_id: uuid.UUID, payload: VehicleUpdateIn) -> VehicleOut:
    return services.update_vehicle(ctx_of(request), vehicle_id, payload)


@router.post("/vehicles/{vehicle_id}/status", response=VehicleOut, summary="Change vehicle status")
@requires("fleet.write")
@idempotent
def set_vehicle_status(request: HttpRequest, vehicle_id: uuid.UUID, payload: AssetStatusIn) -> VehicleOut:
    return services.set_vehicle_status(ctx_of(request), vehicle_id, payload)


@router.get("/trailers", response=TrailerPage, summary="List trailers")
@requires("fleet.read")
def list_trailers(request: HttpRequest, cursor: str | None = None, limit: int | None = None) -> TrailerPage:
    return services.list_trailers(ctx_of(request), cursor=cursor, limit=limit)


@router.post("/trailers", response={201: TrailerOut}, summary="Register a trailer")
@requires("fleet.write")
@idempotent
def create_trailer(request: HttpRequest, payload: TrailerIn) -> Status[TrailerOut]:
    return Status(201, services.create_trailer(ctx_of(request), payload))


@router.post("/trailers/{trailer_id}/status", response=TrailerOut, summary="Change trailer status")
@requires("fleet.write")
@idempotent
def set_trailer_status(request: HttpRequest, trailer_id: uuid.UUID, payload: AssetStatusIn) -> TrailerOut:
    return services.set_trailer_status(ctx_of(request), trailer_id, payload)
