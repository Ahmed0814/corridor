"""fleet public interface (D-005).

Vehicle state: available <-> maintenance, any -> retired (terminal). "Assigned" is derived from an
active trip assignment; an assigned vehicle cannot be put in maintenance or retired.
"""

from __future__ import annotations

import uuid
from typing import Any

from corridor.core.api import ApiError
from corridor.core.lifecycle import assert_state, lock, not_found, rule
from corridor.core.pagination import paginate
from corridor.fleet.models import AssetStatus, Trailer, Vehicle
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
from corridor.identity.schemas import RequestContext, Scope


def _norm_plate(plate: str) -> str:
    return " ".join(plate.upper().split())


def _assigned_trips(vehicle_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    from corridor.trips import services as trips  # lazy: trips depends on fleet

    return trips.active_trip_by_vehicle(vehicle_ids)


def _vehicle_out(v: Vehicle, assigned: dict[uuid.UUID, uuid.UUID]) -> VehicleOut:
    return VehicleOut(
        id=v.id,
        plate=v.plate,
        kind=v.kind,
        make=v.make,
        model=v.model,
        year=v.year,
        status=v.status,
        assigned_trip_id=assigned.get(v.id),
        created_at=v.created_at,
    )


def _visible_vehicles(ctx: RequestContext) -> Any:
    qs = Vehicle.objects.all()
    if ctx.scope == Scope.DRIVER:
        from corridor.trips import services as trips

        return qs.filter(id__in=trips.vehicle_ids_for_driver(ctx.driver_id))
    if ctx.scope != Scope.TENANT:
        return qs.none()
    return qs


def list_vehicles(
    ctx: RequestContext, *, status: str | None, cursor: str | None, limit: int | None
) -> VehiclePage:
    qs = _visible_vehicles(ctx)
    if status:
        qs = qs.filter(status=status)
    rows, nxt = paginate(qs, cursor, limit)
    assigned = _assigned_trips([v.id for v in rows])
    return VehiclePage(items=[_vehicle_out(v, assigned) for v in rows], next_cursor=nxt)


def get_vehicle(ctx: RequestContext, vehicle_id: uuid.UUID) -> VehicleOut:
    v = _visible_vehicles(ctx).filter(id=vehicle_id).first()
    if v is None:
        raise not_found()
    return _vehicle_out(v, _assigned_trips([v.id]))


def create_vehicle(ctx: RequestContext, data: VehicleIn) -> VehicleOut:
    plate = _norm_plate(data.plate)
    if Vehicle.objects.filter(plate=plate).exists():
        raise ApiError(409, "conflict", "A vehicle with this plate already exists.")
    v = Vehicle.for_context(**{**data.model_dump(), "plate": plate})
    v.save()
    return _vehicle_out(v, {})


def update_vehicle(ctx: RequestContext, vehicle_id: uuid.UUID, data: VehicleUpdateIn) -> VehicleOut:
    v = lock(Vehicle.objects.all(), vehicle_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(v, field, value)
    v.save()
    return _vehicle_out(v, _assigned_trips([v.id]))


def set_vehicle_status(ctx: RequestContext, vehicle_id: uuid.UUID, data: AssetStatusIn) -> VehicleOut:
    v = lock(Vehicle.objects.all(), vehicle_id)
    assert_state(v.status, (AssetStatus.AVAILABLE, AssetStatus.MAINTENANCE), f"set status to {data.status}")
    assigned = _assigned_trips([v.id])
    if data.status != "available":
        rule(
            v.id not in assigned,
            "vehicle_assigned",
            "The vehicle is assigned to an open trip.",
            {"trip_id": str(assigned.get(v.id))},
        )
    v.status = data.status
    v.save(update_fields=["status", "updated_at"])
    return _vehicle_out(v, assigned)


def list_trailers(ctx: RequestContext, *, cursor: str | None, limit: int | None) -> TrailerPage:
    if ctx.scope != Scope.TENANT:
        raise not_found()
    rows, nxt = paginate(Trailer.objects.all(), cursor, limit)
    return TrailerPage(
        items=[TrailerOut.model_validate(t, from_attributes=True) for t in rows], next_cursor=nxt
    )


def create_trailer(ctx: RequestContext, data: TrailerIn) -> TrailerOut:
    plate = _norm_plate(data.plate)
    if Trailer.objects.filter(plate=plate).exists():
        raise ApiError(409, "conflict", "A trailer with this plate already exists.")
    t = Trailer.for_context(plate=plate, kind=data.kind)
    t.save()
    return TrailerOut.model_validate(t, from_attributes=True)


def set_trailer_status(ctx: RequestContext, trailer_id: uuid.UUID, data: AssetStatusIn) -> TrailerOut:
    t = lock(Trailer.objects.all(), trailer_id)
    assert_state(t.status, (AssetStatus.AVAILABLE, AssetStatus.MAINTENANCE), f"set status to {data.status}")
    t.status = data.status
    t.save(update_fields=["status", "updated_at"])
    return TrailerOut.model_validate(t, from_attributes=True)


# ---------------------------------------------------------------- used by trips


def assert_vehicle_assignable(vehicle_id: uuid.UUID) -> None:
    v = Vehicle.objects.select_for_update().filter(id=vehicle_id).first()
    if v is None:
        raise not_found("Vehicle not found.")
    rule(
        v.status == AssetStatus.AVAILABLE,
        "vehicle_unavailable",
        f"Vehicle {v.plate} is {v.status}.",
        {"vehicle_id": str(v.id), "status": v.status},
    )


def assert_trailer_assignable(trailer_id: uuid.UUID) -> None:
    t = Trailer.objects.select_for_update().filter(id=trailer_id).first()
    if t is None:
        raise not_found("Trailer not found.")
    rule(t.status == AssetStatus.AVAILABLE, "trailer_unavailable", f"Trailer {t.plate} is {t.status}.")


def plates(vehicle_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Vehicle.objects.filter(id__in=vehicle_ids).values_list("id", "plate"))
