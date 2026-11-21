"""tracking Ninja router (MASTER_PROMPT §5 key endpoints)."""

from __future__ import annotations

import uuid
from datetime import datetime

from django.http import HttpRequest
from ninja import Router

from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.tracking import services
from corridor.tracking.schemas import (
    FleetOut,
    IngestResult,
    LatestLocationOut,
    LocationBatchIn,
    LocationIn,
    TrackOut,
)

router = Router(tags=["tracking"], auth=tenant_auth)


# GPS uploads are deduplicated per event (device + event id), so they do not use Idempotency-Key
# (D-015): a retried batch simply returns those events as "duplicate".
@router.post("/tracking/location", response=IngestResult, summary="Send one GPS location (driver device)")
@requires("tracking.ingest")
def ingest_one(request: HttpRequest, payload: LocationIn) -> IngestResult:
    return services.ingest(ctx_of(request), [payload])


@router.post("/tracking/location/batch", response=IngestResult, summary="Send up to 500 GPS locations")
@requires("tracking.ingest")
def ingest_batch(request: HttpRequest, payload: LocationBatchIn) -> IngestResult:
    return services.ingest(ctx_of(request), payload.events)


@router.get(
    "/vehicles/{vehicle_id}/location",
    response=LatestLocationOut,
    summary="Latest trusted location with freshness, recorded and received times",
)
@requires("tracking.read")
def vehicle_location(request: HttpRequest, vehicle_id: uuid.UUID) -> LatestLocationOut:
    return services.latest_for_vehicle(ctx_of(request), vehicle_id)


@router.get("/trips/{trip_id}/locations", response=TrackOut, summary="GPS track of a trip (with flags)")
@requires("tracking.read")
def trip_locations(
    request: HttpRequest, trip_id: uuid.UUID, after: datetime | None = None, limit: int | None = None
) -> TrackOut:
    return services.trip_track(ctx_of(request), trip_id, after=after, limit=limit)


@router.get("/tracking/fleet", response=FleetOut, summary="Latest location of every vehicle (live map)")
@requires("tracking.read")
def fleet(request: HttpRequest) -> FleetOut:
    return services.fleet_snapshot(ctx_of(request))
