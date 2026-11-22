"""geofencing public interface: geofences, checkpoints and checkpoint detection from GPS.

Detection (MASTER_PROMPT §4.1 "checkpoint detection", Phase 6 DoD "checkpoints and geofences trigger
events") runs inside the GPS ingestion transaction, on the *trusted* points only (no blocking flags),
oldest first. Trusted points are always newer than the vehicle's previous latest point, so an old or
replayed point can never re-open or close a visit.

* first trusted point inside an active checkpoint -> open a visit, trip event ``checkpoint_entered``,
  outbox ``checkpoint.reached``;
* first trusted point outside an open visit -> close it, trip event ``checkpoint_exited``;
* entry into a *border* checkpoint whose geofence is **verified** also moves the trip's in-transit
  shipments to ``at_border`` (system actor) and emits ``border.arrived``. It never clears customs
  (hard rule 8). An unverified border geofence only records the visit, labelled unverified (D-027).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from django.contrib.gis.geos import GEOSGeometry, Polygon
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from corridor.audit import services as audit
from corridor.core.api import ApiError
from corridor.core.lifecycle import lock, not_found, rule
from corridor.events import services as events
from corridor.geofencing.models import Checkpoint, CheckpointVisit, Geofence
from corridor.geofencing.schemas import (
    CheckpointIn,
    CheckpointOut,
    CheckpointVisitOut,
    GeofenceIn,
    GeofenceOut,
    TrustedPoint,
)
from corridor.identity.schemas import RequestContext, Scope


def _trips() -> Any:
    from corridor.trips import services as trips  # lazy: trips -> tracking -> geofencing

    return trips


def _shipments() -> Any:
    from corridor.shipments import services as shipments

    return shipments


def _tenant_only(ctx: RequestContext) -> None:
    if ctx.scope != Scope.TENANT:
        raise not_found()


# --------------------------------------------------------------------------- output


def _geofence_out(g: Geofence) -> GeofenceOut:
    return GeofenceOut(
        id=g.id,
        name=g.name,
        kind=g.kind,
        shape=g.shape,
        polygon=[[round(x, 6), round(y, 6)] for x, y in g.area.exterior_ring.coords],
        source_note=g.source_note,
        verified=g.verified_at is not None,
        verified_at=g.verified_at,
        is_active=g.is_active,
        created_at=g.created_at,
    )


def _checkpoint_out(c: Checkpoint, g: Geofence) -> CheckpointOut:
    return CheckpointOut(
        id=c.id,
        geofence_id=g.id,
        geofence_name=g.name,
        name=c.name,
        is_border=c.is_border,
        verified=g.verified_at is not None,
        is_active=c.is_active,
        created_at=c.created_at,
    )


# --------------------------------------------------------------------------- geofences


def _circle(lat: float, lng: float, radius_m: float) -> Polygon:
    """A true metric circle (geodesic buffer on the geography type), as a 32-sided polygon."""
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_AsText(ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, 8)::geometry)",
            [lng, lat, radius_m],
        )
        row = cur.fetchone()
    geom = GEOSGeometry(row[0], srid=4326)
    if not isinstance(geom, Polygon):  # pragma: no cover - a point buffer is always a polygon
        raise ApiError(422, "invalid_geometry", "Could not build the circle.")
    return geom


def _polygon(points: Sequence[Any]) -> Polygon:
    ring = [(p.lng, p.lat) for p in points]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    poly = Polygon(ring, srid=4326)
    if not poly.valid:
        raise ApiError(422, "invalid_geometry", "The polygon is not valid (for example, its edges cross).")
    return poly


def list_geofences(ctx: RequestContext) -> list[GeofenceOut]:
    _tenant_only(ctx)
    return [_geofence_out(g) for g in Geofence.objects.order_by("name")]


def create_geofence(ctx: RequestContext, data: GeofenceIn) -> GeofenceOut:
    _tenant_only(ctx)
    if data.polygon is not None:
        area, shape = _polygon(data.polygon), "polygon"
    else:
        if data.center is None or data.radius_m is None:  # the schema validator guarantees this
            raise ApiError(422, "validation_error", "Give either a polygon or a centre and radius.")
        area, shape = _circle(data.center.lat, data.center.lng, data.radius_m), "circle"
    g = Geofence.for_context(
        name=data.name,
        kind=data.kind,
        area=area,
        shape=shape,
        source_note=data.source_note,
        created_by=ctx.user_id,
    )
    try:
        with transaction.atomic():
            g.save()
    except IntegrityError as exc:
        raise ApiError(409, "conflict", "A geofence with this name already exists.") from exc
    return _geofence_out(g)


def verify_geofence(ctx: RequestContext, geofence_id: uuid.UUID) -> GeofenceOut:
    """An operator confirms the outline matches the real place (D-027). Audited."""
    _tenant_only(ctx)
    g: Geofence = lock(Geofence.objects.all(), geofence_id)
    rule(g.verified_at is None, "already_verified", "This geofence is already verified.")
    g.verified_at, g.verified_by = timezone.now(), ctx.user_id
    g.save(update_fields=["verified_at", "verified_by", "updated_at"])
    audit.record(
        "geofence.verified",
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        target_type="geofence",
        target_id=g.id,
        metadata={"name": g.name, "kind": g.kind},
    )
    return _geofence_out(g)


def set_geofence_active(ctx: RequestContext, geofence_id: uuid.UUID, *, active: bool) -> GeofenceOut:
    _tenant_only(ctx)
    g: Geofence = lock(Geofence.objects.all(), geofence_id)
    g.is_active = active
    g.save(update_fields=["is_active", "updated_at"])
    return _geofence_out(g)


# --------------------------------------------------------------------------- checkpoints


def list_checkpoints(ctx: RequestContext) -> list[CheckpointOut]:
    _tenant_only(ctx)
    rows = list(Checkpoint.objects.order_by("name"))
    fences = {g.id: g for g in Geofence.objects.filter(id__in={c.geofence_id for c in rows})}
    return [_checkpoint_out(c, fences[c.geofence_id]) for c in rows]


def create_checkpoint(ctx: RequestContext, data: CheckpointIn) -> CheckpointOut:
    _tenant_only(ctx)
    g = Geofence.objects.filter(id=data.geofence_id).first()
    if g is None:
        raise not_found("Geofence not found.")
    c = Checkpoint.for_context(geofence=g, name=data.name, is_border=data.is_border, created_by=ctx.user_id)
    try:
        with transaction.atomic():
            c.save()
    except IntegrityError as exc:
        raise ApiError(409, "conflict", "A checkpoint with this name already exists.") from exc
    return _checkpoint_out(c, g)


def set_checkpoint_active(ctx: RequestContext, checkpoint_id: uuid.UUID, *, active: bool) -> CheckpointOut:
    _tenant_only(ctx)
    c: Checkpoint = lock(Checkpoint.objects.all(), checkpoint_id)
    c.is_active = active
    c.save(update_fields=["is_active"])
    return _checkpoint_out(c, Geofence.objects.get(id=c.geofence_id))


def trip_visits(ctx: RequestContext, trip_id: uuid.UUID) -> list[CheckpointVisitOut]:
    _trips().get_trip(ctx, trip_id)  # 404 unless the caller may see this trip
    return _visits_out(list(CheckpointVisit.objects.filter(trip_id=trip_id).order_by("entered_at", "id")))


def visits_for_trips(trip_ids: list[uuid.UUID]) -> list[CheckpointVisitOut]:
    """For other modules that already checked visibility (shipment tracking views)."""
    return _visits_out(
        list(CheckpointVisit.objects.filter(trip_id__in=trip_ids).order_by("entered_at", "id"))
    )


def _visits_out(rows: list[CheckpointVisit]) -> list[CheckpointVisitOut]:
    cps = {c.id: c for c in Checkpoint.objects.filter(id__in={r.checkpoint_id for r in rows})}
    return [
        CheckpointVisitOut(
            id=r.id,
            trip_id=r.trip_id,
            checkpoint_id=r.checkpoint_id,
            checkpoint_name=cps[r.checkpoint_id].name,
            is_border=cps[r.checkpoint_id].is_border,
            geofence_verified=r.geofence_verified,
            entered_at=r.entered_at,
            exited_at=r.exited_at,
        )
        for r in rows
    ]


# --------------------------------------------------------------------------- detection

_CONTAINING = """
SELECT p.idx, c.id
FROM unnest(%s::float8[], %s::float8[]) WITH ORDINALITY AS p(lng, lat, idx)
JOIN geofences g ON g.is_active AND ST_Covers(g.area, ST_SetSRID(ST_MakePoint(p.lng, p.lat), 4326))
JOIN checkpoints c ON c.geofence_id = g.id AND c.is_active
"""


def process_trusted_points(trip_id: uuid.UUID, vehicle_id: uuid.UUID, points: list[TrustedPoint]) -> int:
    """Open/close checkpoint visits for one trip. Called by tracking.ingest in its transaction (RLS
    limits every table here to the current tenant). Returns the number of entries + exits."""
    if not points:
        return 0
    points = sorted(points, key=lambda p: p.recorded_at)
    with connection.cursor() as cur:
        cur.execute(_CONTAINING, [[p.lng for p in points], [p.lat for p in points]])
        inside_by_idx: dict[int, set[uuid.UUID]] = {}
        for idx, cp_id in cur.fetchall():
            inside_by_idx.setdefault(int(idx) - 1, set()).add(cp_id)

    open_visits = {
        v.checkpoint_id: v
        for v in CheckpointVisit.objects.select_for_update().filter(trip_id=trip_id, exited_at__isnull=True)
    }
    if not open_visits and not inside_by_idx:
        return 0
    involved = set(open_visits) | {cp for s in inside_by_idx.values() for cp in s}
    checkpoints = {c.id: c for c in Checkpoint.objects.filter(id__in=involved)}
    fences = {g.id: g for g in Geofence.objects.filter(id__in={c.geofence_id for c in checkpoints.values()})}

    changes = 0
    for i, p in enumerate(points):
        inside = inside_by_idx.get(i, set())
        for cp_id in [cp for cp in open_visits if cp not in inside]:
            visit = open_visits.pop(cp_id)
            visit.exited_at, visit.exit_event_id = p.recorded_at, p.event_id
            visit.save(update_fields=["exited_at", "exit_event_id"])
            _trips().record_system_event(
                trip_id,
                "checkpoint_exited",
                {
                    "checkpoint_id": str(cp_id),
                    "checkpoint": checkpoints[cp_id].name,
                    "at": p.recorded_at.isoformat(),
                },
            )
            changes += 1
        for cp_id in sorted(inside - set(open_visits), key=str):
            cp = checkpoints[cp_id]
            verified = fences[cp.geofence_id].verified_at is not None
            visit = CheckpointVisit.for_context(
                trip_id=trip_id,
                checkpoint=cp,
                vehicle_id=vehicle_id,
                entered_at=p.recorded_at,
                entry_event_id=p.event_id,
                geofence_verified=verified,
            )
            visit.save()
            open_visits[cp_id] = visit
            _on_entry(trip_id, vehicle_id, cp, verified, p, visit.id)
            changes += 1
    return changes


def _on_entry(
    trip_id: uuid.UUID, vehicle_id: uuid.UUID, cp: Checkpoint, verified: bool, p: TrustedPoint, visit_id: int
) -> None:
    payload = {
        "trip_id": str(trip_id),
        "vehicle_id": str(vehicle_id),
        "checkpoint_id": str(cp.id),
        "checkpoint": cp.name,
        "is_border": cp.is_border,
        "geofence_verified": verified,
        "visit_id": visit_id,
        "recorded_at": p.recorded_at.isoformat(),
        "gps_event_id": str(p.event_id),
    }
    _trips().record_system_event(trip_id, "checkpoint_entered", payload)
    events.emit("checkpoint.reached", aggregate_type="trip", aggregate_id=trip_id, payload=payload)
    if cp.is_border and verified:
        # Arrival only. Clearance stays a separate, permissioned human action (hard rule 8).
        _shipments().border_arrival_from_geofence(
            _trips().shipment_ids_for_trip(trip_id),
            border=cp.name,
            trip_id=trip_id,
            checkpoint_id=cp.id,
            gps_event_id=p.event_id,
            recorded_at=p.recorded_at,
        )
