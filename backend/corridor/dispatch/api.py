"""dispatch Ninja router: planning across shipments, fleet, drivers and trips (D-052)."""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.api import ApiError
from corridor.core.idempotency import idempotent
from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.trips import services as trips
from corridor.trips.schemas import DispatchPlanIn, TripOut

router = Router(tags=["dispatch"], auth=tenant_auth)


@router.post(
    "/dispatch",
    response={201: TripOut},
    summary="Create a trip, assign vehicle + driver and dispatch its shipments in one step",
)
@requires("shipments.dispatch")
@idempotent
def plan_and_dispatch(request: HttpRequest, payload: DispatchPlanIn) -> Status[TripOut]:
    ctx = ctx_of(request)
    if not ctx.has("trips.assign"):
        raise ApiError(403, "forbidden", "Dispatch also requires trips.assign.")
    return Status(201, trips.plan_and_dispatch(ctx, payload))
