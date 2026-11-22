"""tracking public interface: GPS ingestion, latest location, freshness, track history.

Pipeline (MASTER_PROMPT §4.1): authenticate -> tenant from membership -> driver from membership ->
authorized tracking session -> per-event validation -> store history (dedupe) -> conditional update
of the latest trusted location -> realtime push after commit.

Rejected (not stored): invalid coordinates/accuracy, timestamps in the future or older than the
retention window, no authorized session, vehicle/device mismatch, reused event ids.
Flagged (stored, never trusted as latest when blocking): low accuracy, out of order, impossible
speed, clock skew; informational: while paused, late upload, network fix.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from django.db import connection, transaction
from django.utils import timezone

from corridor.core.api import ApiError
from corridor.core.lifecycle import not_found
from corridor.events import services as events
from corridor.identity.schemas import RequestContext, Scope
from corridor.realtime import services as realtime
from corridor.tracking.models import (
    Flag,
    GpsLocationEvent,
    SessionStatus,
    TrackingSession,
    VehicleLatestLocation,
)
from corridor.tracking.schemas import (
    FleetOut,
    IngestResult,
    LatestLocationOut,
    LocationIn,
    Rejected,
    TrackOut,
    TrackPointOut,
)

# Validation limits (tenant-independent; see docs/database/erd.md "Validation flags").
FUTURE_REJECT = timedelta(minutes=5)  # recorded_at further ahead than this is rejected
CLOCK_SKEW_FLAG = timedelta(seconds=60)  # recorded_at ahead of server receipt by more is flagged
LATE_UPLOAD = timedelta(hours=1)
LOW_ACCURACY_M = 100.0
MAX_ACCURACY_M = 100_000.0  # beyond this the value is nonsense: rejected
MAX_SPEED_KMH = 150.0
SESSION_GRACE = timedelta(hours=24)  # late uploads after a session closed (D-013)
SESSION_START_SLACK = timedelta(minutes=2)  # device clocks slightly behind the server at start
RETENTION_MONTHS = 12

DEFAULT_THRESHOLDS = {
    "freshness_live_seconds": 120,
    "freshness_delayed_seconds": 600,
    "freshness_stale_seconds": 3600,
}


def _trips() -> Any:
    from corridor.trips import services as trips  # lazy: trips calls tracking on start/pause/stop

    return trips


# --------------------------------------------------------------------------- sessions (trips hooks)


def open_session(trip_id: uuid.UUID, driver_id: uuid.UUID, vehicle_id: uuid.UUID) -> uuid.UUID:
    """Called by trips.start_trip in the same transaction."""
    s = TrackingSession.for_context(
        trip_id=trip_id, driver_id=driver_id, vehicle_id=vehicle_id, opened_at=timezone.now()
    )
    s.save()
    events.emit(
        "tracking.session.started",
        aggregate_type="tracking_session",
        aggregate_id=s.id,
        payload={
            "session_id": str(s.id),
            "trip_id": str(trip_id),
            "driver_id": str(driver_id),
            "vehicle_id": str(vehicle_id),
        },
    )
    return s.id


def set_session_paused(trip_id: uuid.UUID, paused: bool) -> None:
    TrackingSession.objects.filter(trip_id=trip_id).exclude(status=SessionStatus.CLOSED).update(
        status=SessionStatus.PAUSED if paused else SessionStatus.ACTIVE
    )


def close_session(trip_id: uuid.UUID) -> None:
    for s in (
        TrackingSession.objects.select_for_update()
        .filter(trip_id=trip_id)
        .exclude(status=SessionStatus.CLOSED)
    ):
        s.status, s.closed_at = SessionStatus.CLOSED, timezone.now()
        s.save(update_fields=["status", "closed_at"])
        events.emit(
            "tracking.session.stopped",
            aggregate_type="tracking_session",
            aggregate_id=s.id,
            payload={"session_id": str(s.id), "trip_id": str(trip_id)},
        )


# --------------------------------------------------------------------------- freshness


def thresholds() -> dict[str, int]:
    from corridor.tenants import services as tenants

    configured = tenants.current_profile().settings
    return {k: int(configured.get(k, v)) for k, v in DEFAULT_THRESHOLDS.items()}


Freshness = Literal["live", "delayed", "stale", "offline"]


def freshness(
    recorded_at: datetime, *, now: datetime, session_active: bool, limits: dict[str, int]
) -> tuple[Freshness, int]:
    """LIVE / DELAYED / STALE / OFFLINE from the age of the *recorded* time (MASTER_PROMPT §2).
    A point is never live when its tracking session is not active."""
    age = max(0, int((now - recorded_at).total_seconds()))
    if not session_active or age > limits["freshness_stale_seconds"]:
        return "offline", age
    if age <= limits["freshness_live_seconds"]:
        return "live", age
    if age <= limits["freshness_delayed_seconds"]:
        return "delayed", age
    return "stale", age


# --------------------------------------------------------------------------- ingestion


@dataclass
class _Candidate:
    e: LocationIn
    session: TrackingSession
    flags: int = 0


def _retention_cutoff(now: datetime) -> datetime:
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    y, m = month_start.year, month_start.month - RETENTION_MONTHS
    while m <= 0:
        y, m = y - 1, m + 12
    return month_start.replace(year=y, month=m)


def _basic_rejection(e: LocationIn, now: datetime) -> str | None:
    if not (math.isfinite(e.latitude) and math.isfinite(e.longitude)) or not (
        -90.0 <= e.latitude <= 90.0 and -180.0 <= e.longitude <= 180.0
    ):
        return "invalid_coordinates"
    if e.latitude == 0.0 and e.longitude == 0.0:
        return "invalid_coordinates"  # "null island": an unset fix, never a real corridor position
    if e.accuracy_meters is not None and not (0.0 <= e.accuracy_meters <= MAX_ACCURACY_M):
        return "invalid_accuracy"
    if e.recorded_at.tzinfo is None:
        return "timestamp_without_timezone"
    if e.recorded_at > now + FUTURE_REJECT:
        return "future_timestamp"
    if e.recorded_at < _retention_cutoff(now):
        return "too_old"
    return None


def _session_for(
    sessions: list[TrackingSession], recorded_at: datetime, now: datetime
) -> TrackingSession | str:
    if not sessions:
        return "no_session"
    for s in sessions:  # newest first
        if recorded_at < s.opened_at - SESSION_START_SLACK:
            continue
        if s.status != SessionStatus.CLOSED:
            return s
        if s.closed_at is None:  # closed without a time cannot happen; treat as still open
            return s
        if recorded_at > s.closed_at:
            continue
        if now > s.closed_at + SESSION_GRACE:
            return "session_closed"
        return s  # late upload of a point recorded while the session was open (D-013)
    return "outside_session_window"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class _Point:
    lat: float
    lng: float
    recorded_at: datetime


def ingest(ctx: RequestContext, batch: list[LocationIn]) -> IngestResult:
    if ctx.scope != Scope.DRIVER or ctx.driver_id is None:
        raise ApiError(403, "forbidden", "Only a driver's device can send locations for its own session.")
    now = timezone.now()
    rejected: list[Rejected] = []

    sessions_by_trip: dict[uuid.UUID, list[TrackingSession]] = {}
    for s in (
        TrackingSession.objects.select_for_update()
        .filter(trip_id__in={e.trip_id for e in batch}, driver_id=ctx.driver_id)
        .order_by("-opened_at")
    ):
        sessions_by_trip.setdefault(s.trip_id, []).append(s)

    candidates: list[_Candidate] = []
    for e in batch:
        reason = _basic_rejection(e, now)
        if reason is None:
            found = _session_for(sessions_by_trip.get(e.trip_id, []), e.recorded_at, now)
            if isinstance(found, str):
                reason = found
            elif found.vehicle_id != e.vehicle_id:
                reason = "vehicle_mismatch"
            elif found.device_id is not None and found.device_id != e.device_id:
                reason = "device_mismatch"
            else:
                if found.device_id is None:  # first upload binds the device to the session (D-057)
                    found.device_id = e.device_id
                    found.save(update_fields=["device_id"])
                candidates.append(_Candidate(e, found))
        if reason is not None:
            rejected.append(Rejected(event_id=e.event_id, reason=reason))

    duplicate: list[uuid.UUID] = []
    candidates = _drop_known(candidates, duplicate, rejected)
    _flag(candidates, now)
    inserted = _insert(ctx, candidates, now)
    duplicate += [c.e.event_id for c in candidates if c.e.event_id not in inserted]  # lost a race
    stored = [c for c in candidates if c.e.event_id in inserted]
    _update_latest(ctx, stored, now)
    _after_trusted_points(stored)

    return IngestResult(
        accepted=[c.e.event_id for c in stored],
        duplicate=duplicate,
        rejected=rejected,
        flagged={str(c.e.event_id): Flag.names(c.flags) for c in stored if c.flags},
    )


def _drop_known(
    candidates: list[_Candidate], duplicate: list[uuid.UUID], rejected: list[Rejected]
) -> list[_Candidate]:
    """Duplicates (same device + event id + recorded_at) are acknowledged so the app can delete them;
    the same event id with a different recorded_at is a reuse and is rejected (D-012)."""
    if not candidates:
        return []
    known = {
        (d, ev): rec
        for d, ev, rec in GpsLocationEvent.objects.filter(
            device_id__in={c.e.device_id for c in candidates}, event_id__in={c.e.event_id for c in candidates}
        ).values_list("device_id", "event_id", "recorded_at")
    }
    seen: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {}
    kept = []
    for c in candidates:
        k = (c.e.device_id, c.e.event_id)
        previous = known.get(k) or seen.get(k)
        if previous is None:
            seen[k] = c.e.recorded_at
            kept.append(c)
        elif previous == c.e.recorded_at:
            duplicate.append(c.e.event_id)
        else:
            rejected.append(Rejected(event_id=c.e.event_id, reason="event_id_reused"))
    return kept


def _flag(candidates: list[_Candidate], now: datetime) -> None:
    latest = {
        v.vehicle_id: _Point(v.point.y, v.point.x, v.recorded_at)
        for v in VehicleLatestLocation.objects.filter(vehicle_id__in={c.e.vehicle_id for c in candidates})
    }
    candidates.sort(key=lambda c: (str(c.e.vehicle_id), c.e.recorded_at, c.e.sequence_number or 0))
    for c in candidates:
        e = c.e
        if e.accuracy_meters is not None and e.accuracy_meters > LOW_ACCURACY_M:
            c.flags |= Flag.LOW_ACCURACY
        if e.recorded_at > now + CLOCK_SKEW_FLAG:
            c.flags |= Flag.CLOCK_SKEW
        if c.session.status == SessionStatus.PAUSED:
            c.flags |= Flag.WHILE_PAUSED
        if now - e.recorded_at > LATE_UPLOAD:
            c.flags |= Flag.LATE_UPLOAD
        if e.source == "phone_network":
            c.flags |= Flag.NETWORK_FIX
        prev = latest.get(e.vehicle_id)
        if prev is not None:
            if e.recorded_at <= prev.recorded_at:
                c.flags |= Flag.OUT_OF_ORDER  # an older point must never become the latest (hard rule 4)
            else:
                dt = (e.recorded_at - prev.recorded_at).total_seconds()
                if _haversine_m(prev.lat, prev.lng, e.latitude, e.longitude) / dt * 3.6 > MAX_SPEED_KMH:
                    c.flags |= Flag.IMPOSSIBLE_SPEED
        if not c.flags & Flag.BLOCKING:
            latest[e.vehicle_id] = _Point(e.latitude, e.longitude, e.recorded_at)  # new trusted baseline


_COLS = (
    "tenant_id, event_id, device_id, session_id, trip_id, vehicle_id, driver_id, sequence_number, point, "
    "accuracy_m, speed_mps, heading_deg, recorded_at, received_at, source, flags"
)
_ROW = "(%s, %s, %s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s, %s)"


def _insert(ctx: RequestContext, candidates: list[_Candidate], now: datetime) -> set[uuid.UUID]:
    """One multi-row INSERT ... ON CONFLICT DO NOTHING RETURNING event_id (D-012): ids not returned
    were duplicates inserted concurrently."""
    if not candidates:
        return set()
    params: list[Any] = []
    for c in candidates:
        e, s = c.e, c.session
        params += [
            ctx.tenant_id,
            e.event_id,
            e.device_id,
            s.id,
            s.trip_id,
            s.vehicle_id,
            s.driver_id,
            e.sequence_number,
            e.longitude,
            e.latitude,
            e.accuracy_meters,
            e.speed,
            e.heading,
            e.recorded_at,
            now,
            e.source,
            c.flags,
        ]
    # Built only from constant column names and %s placeholders; every value is a bound parameter.
    values = ", ".join([_ROW] * len(candidates))
    sql = (
        f"INSERT INTO gps_location_events ({_COLS}) VALUES {values} ON CONFLICT DO NOTHING RETURNING event_id"  # noqa: S608
    )
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return {row[0] for row in cur.fetchall()}


_UPSERT = """
INSERT INTO vehicle_latest_locations (vehicle_id, tenant_id, event_id, trip_id, session_id, driver_id, point,
    accuracy_m, speed_mps, heading_deg, recorded_at, received_at, source)
VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, %s)
ON CONFLICT (vehicle_id) DO UPDATE SET
    event_id = EXCLUDED.event_id, trip_id = EXCLUDED.trip_id, session_id = EXCLUDED.session_id,
    driver_id = EXCLUDED.driver_id, point = EXCLUDED.point, accuracy_m = EXCLUDED.accuracy_m,
    speed_mps = EXCLUDED.speed_mps, heading_deg = EXCLUDED.heading_deg, recorded_at = EXCLUDED.recorded_at,
    received_at = EXCLUDED.received_at, source = EXCLUDED.source
WHERE vehicle_latest_locations.recorded_at < EXCLUDED.recorded_at
RETURNING vehicle_id
"""


def _update_latest(ctx: RequestContext, stored: list[_Candidate], now: datetime) -> None:
    """Conditional upsert: only the newest trusted point per vehicle, and only if it is newer than the
    current latest (the WHERE clause makes this safe against concurrent and out-of-order uploads)."""
    best: dict[uuid.UUID, _Candidate] = {}
    for c in stored:
        if c.flags & Flag.BLOCKING:
            continue
        cur_best = best.get(c.e.vehicle_id)
        if cur_best is None or c.e.recorded_at > cur_best.e.recorded_at:
            best[c.e.vehicle_id] = c
    updates = []
    with connection.cursor() as cur:
        for vehicle_id, c in best.items():
            e, s = c.e, c.session
            cur.execute(
                _UPSERT,
                [
                    vehicle_id,
                    ctx.tenant_id,
                    e.event_id,
                    s.trip_id,
                    s.id,
                    s.driver_id,
                    e.longitude,
                    e.latitude,
                    e.accuracy_meters,
                    e.speed,
                    e.heading,
                    e.recorded_at,
                    now,
                    e.source,
                ],
            )
            if cur.fetchone() is not None:
                updates.append(
                    {
                        "vehicle_id": str(vehicle_id),
                        "trip_id": str(s.trip_id),
                        "latitude": e.latitude,
                        "longitude": e.longitude,
                        "accuracy_meters": e.accuracy_meters,
                        "speed": e.speed,
                        "heading": e.heading,
                        "recorded_at": e.recorded_at.isoformat(),
                        "received_at": now.isoformat(),
                    }
                )
    if updates and ctx.tenant_id is not None:
        tenant_id = ctx.tenant_id
        # Non-critical side effect after commit (D-011): if Redis is down the location is still stored.
        transaction.on_commit(lambda: _broadcast(tenant_id, updates))


def _broadcast(tenant_id: uuid.UUID, updates: list[dict[str, Any]]) -> None:
    for u in updates:
        try:
            realtime.broadcast_fleet(tenant_id, u)
        except Exception:  # realtime is best effort; clients also poll
            import structlog

            structlog.get_logger(__name__).warning("realtime_broadcast_failed", exc_info=True)
            return


# --------------------------------------------------------------------------- reads


def _session_activity(session_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, bool]:
    ids = [s for s in session_ids if s]
    return {
        sid: status != SessionStatus.CLOSED
        for sid, status in TrackingSession.objects.filter(id__in=ids).values_list("id", "status")
    }


def _latest_out(
    v: VehicleLatestLocation, *, plate: str | None, active: bool, now: datetime, limits: dict[str, int]
) -> LatestLocationOut:
    state, age = freshness(v.recorded_at, now=now, session_active=active, limits=limits)
    return LatestLocationOut(
        vehicle_id=v.vehicle_id,
        vehicle_plate=plate,
        trip_id=v.trip_id,
        driver_id=v.driver_id,
        latitude=v.point.y,
        longitude=v.point.x,
        accuracy_meters=v.accuracy_m,
        speed=v.speed_mps,
        heading=v.heading_deg,
        recorded_at=v.recorded_at,
        received_at=v.received_at,
        source=v.source,
        freshness=state,
        age_seconds=age,
        session_active=active,
    )


def latest_for_vehicle(ctx: RequestContext, vehicle_id: uuid.UUID) -> LatestLocationOut:
    from corridor.fleet import services as fleet

    if ctx.scope == Scope.DRIVER:
        if vehicle_id not in _trips().vehicle_ids_for_driver(ctx.driver_id):
            raise not_found()
    elif ctx.scope != Scope.TENANT:
        raise not_found()
    plates = fleet.plates([vehicle_id])
    if vehicle_id not in plates:
        raise not_found()
    v = VehicleLatestLocation.objects.filter(vehicle_id=vehicle_id).first()
    if v is None:
        raise ApiError(404, "no_location", "No location has been received for this vehicle yet.")
    active = _session_activity([v.session_id]).get(v.session_id, False) if v.session_id else False
    return _latest_out(
        v, plate=plates.get(vehicle_id), active=active, now=timezone.now(), limits=thresholds()
    )


def fleet_snapshot(ctx: RequestContext) -> FleetOut:
    from corridor.fleet import services as fleet

    if ctx.scope != Scope.TENANT:
        raise not_found()
    rows = list(VehicleLatestLocation.objects.all())
    plates = fleet.plates([r.vehicle_id for r in rows])
    activity = _session_activity(r.session_id for r in rows)
    now, limits = timezone.now(), thresholds()
    vehicles = [
        _latest_out(
            r,
            plate=plates.get(r.vehicle_id),
            active=bool(r.session_id and activity.get(r.session_id)),
            now=now,
            limits=limits,
        )
        for r in rows
    ]
    vehicles.sort(key=lambda x: x.age_seconds)
    return FleetOut(vehicles=vehicles, thresholds=limits, generated_at=now)


def trip_track(
    ctx: RequestContext, trip_id: uuid.UUID, *, after: datetime | None, limit: int | None
) -> TrackOut:
    _trips().get_trip(ctx, trip_id)  # 404 unless the caller may see this trip (tenant roles, own driver)
    limit = min(max(limit or 1000, 1), 5000)
    qs = GpsLocationEvent.objects.filter(trip_id=trip_id).order_by("recorded_at", "id")
    if after is not None:
        qs = qs.filter(recorded_at__gt=after)
    rows = list(qs[: limit + 1])
    points = [
        TrackPointOut(
            event_id=r.event_id,
            latitude=r.point.y,
            longitude=r.point.x,
            accuracy_meters=r.accuracy_m,
            speed=r.speed_mps,
            heading=r.heading_deg,
            recorded_at=r.recorded_at,
            received_at=r.received_at,
            source=r.source,
            flags=Flag.names(r.flags),
        )
        for r in rows[:limit]
    ]
    return TrackOut(
        trip_id=trip_id, points=points, next_after=points[-1].recorded_at if len(rows) > limit else None
    )


def _after_trusted_points(stored: list[_Candidate]) -> None:
    """Phase 6 hooks, in the ingestion transaction: checkpoint/geofence detection and ETA.

    Only trusted points (no blocking flag) are used. They are always newer than the vehicle's previous
    latest point, so a late or replayed point can never re-trigger a checkpoint or move an ETA back.
    """
    from corridor.geofencing import services as geofencing
    from corridor.geofencing.schemas import TrustedPoint
    from corridor.shipments import services as shipments

    by_trip: dict[tuple[uuid.UUID, uuid.UUID], list[_Candidate]] = {}
    for c in stored:
        if not c.flags & Flag.BLOCKING:
            by_trip.setdefault((c.session.trip_id, c.session.vehicle_id), []).append(c)
    for (trip_id, vehicle_id), items in by_trip.items():
        items.sort(key=lambda c: c.e.recorded_at)
        geofencing.process_trusted_points(
            trip_id,
            vehicle_id,
            [
                TrustedPoint(
                    event_id=c.e.event_id, lat=c.e.latitude, lng=c.e.longitude, recorded_at=c.e.recorded_at
                )
                for c in items
            ],
        )
        last = items[-1].e
        shipments.recompute_eta_for_trip(
            trip_id, lat=last.latitude, lng=last.longitude, recorded_at=last.recorded_at
        )


@dataclass(frozen=True)
class LatestPoint:
    latitude: float
    longitude: float
    recorded_at: datetime
    received_at: datetime
    freshness: Freshness


def latest_point(vehicle_id: uuid.UUID) -> LatestPoint | None:
    """The vehicle's latest trusted point with freshness, for internal callers that already enforced
    access (e.g. a public tracking link resolved to this tenant). Requires a tenant context."""
    v = VehicleLatestLocation.objects.filter(vehicle_id=vehicle_id).first()
    if v is None:
        return None
    active = _session_activity([v.session_id]).get(v.session_id, False) if v.session_id else False
    state, _ = freshness(v.recorded_at, now=timezone.now(), session_active=active, limits=thresholds())
    return LatestPoint(v.point.y, v.point.x, v.recorded_at, v.received_at, state)
