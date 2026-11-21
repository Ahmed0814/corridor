"""Phase 4: GPS ingestion, validation, latest location, freshness, partitions, retention, realtime.

MASTER_PROMPT §8 "GPS": valid, invalid coordinates, low accuracy, duplicate, old, future,
out-of-order, impossible speed, unauthorized vehicle, closed trip, stale location,
older-event-cannot-overwrite.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import connection, connections
from django.utils import timezone

from corridor.core.tenancy import tenant_context
from corridor.realtime.services import fleet_group
from corridor.tracking import services as tracking
from tests.support import World, client_for
from tests.test_dispatch_race import in_thread
from tests.test_logistics import Setup, dispatched, err, ok, post, s  # noqa: F401  (s is a fixture)

pytestmark = pytest.mark.django_db

DEVICE = uuid.UUID("11111111-2222-3333-4444-555555555555")
DJIBOUTI = (11.594, 43.148)


@pytest.fixture
def trip(s: Setup) -> Any:
    """A started trip: the tracking session is open for the alpha driver and vehicle."""
    _, t = dispatched(s)
    return ok(post(s.driver, f"/trips/{t['id']}/start"))


def ev(
    trip: dict[str, Any],
    s: Setup,
    *,
    at: datetime | None = None,
    lat: float = DJIBOUTI[0],
    lng: float = DJIBOUTI[1],
    accuracy: float | None = 8.0,
    device: uuid.UUID = DEVICE,
    vehicle: str | None = None,
    event_id: uuid.UUID | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "event_id": str(event_id or uuid.uuid4()),
        "device_id": str(device),
        "trip_id": trip["id"],
        "vehicle_id": vehicle or s.vehicle_id,
        "latitude": lat,
        "longitude": lng,
        "accuracy_meters": accuracy,
        "recorded_at": (at or timezone.now()).isoformat(),
        **extra,
    }


def send(s: Setup, *events: dict[str, Any], client: Any = None) -> Any:
    return ok((client or s.driver).post("/tracking/location/batch", {"events": list(events)}))


def latest(s: Setup) -> Any:
    return ok(s.ops.get(f"/vehicles/{s.vehicle_id}/location"))


# --------------------------------------------------------------------------- ingestion basics


def test_valid_single_and_batch_ingestion(s: Setup, trip: dict[str, Any]) -> None:
    now = timezone.now()
    single = ev(trip, s, at=now - timedelta(seconds=30))
    r = ok(s.driver.post("/tracking/location", single))
    assert r == {"accepted": [single["event_id"]], "duplicate": [], "rejected": [], "flagged": {}}
    batch = [
        ev(trip, s, at=now - timedelta(seconds=20 - i * 5), lat=DJIBOUTI[0] + i * 0.0005) for i in range(3)
    ]
    r = send(s, *batch)
    assert sorted(r["accepted"]) == sorted(e["event_id"] for e in batch) and not r["rejected"]
    loc = latest(s)
    assert loc["latitude"] == pytest.approx(batch[-1]["latitude"])
    assert loc["freshness"] == "live" and loc["session_active"] is True
    assert loc["recorded_at"] and loc["received_at"]  # both always shown (hard rule 3)
    track = ok(s.ops.get(f"/trips/{trip['id']}/locations"))
    assert len(track["points"]) == 4 and track["points"][0]["event_id"] == single["event_id"]


def test_invalid_coordinates_are_rejected_per_event(s: Setup, trip: dict[str, Any]) -> None:
    good = ev(trip, s)
    bad = [
        ev(trip, s, lat=95.0),
        ev(trip, s, lng=-200.0),
        ev(trip, s, lat=0.0, lng=0.0),
        ev(trip, s, accuracy=-5.0),
    ]
    r = send(s, good, *bad)
    assert r["accepted"] == [good["event_id"]]
    assert sorted(x["reason"] for x in r["rejected"]) == sorted(
        ["invalid_coordinates", "invalid_coordinates", "invalid_coordinates", "invalid_accuracy"]
    )


def test_low_accuracy_is_stored_but_never_trusted(s: Setup, trip: dict[str, Any]) -> None:
    first = ev(trip, s, at=timezone.now() - timedelta(seconds=60))
    send(s, first)
    fuzzy = ev(trip, s, at=timezone.now() - timedelta(seconds=10), lat=DJIBOUTI[0] + 0.01, accuracy=450.0)
    r = send(s, fuzzy)
    assert r["accepted"] == [fuzzy["event_id"]] and r["flagged"] == {fuzzy["event_id"]: ["low_accuracy"]}
    assert latest(s)["latitude"] == pytest.approx(first["latitude"])  # unchanged


def test_duplicates_are_acknowledged_and_reused_ids_rejected(s: Setup, trip: dict[str, Any]) -> None:
    e = ev(trip, s, at=timezone.now() - timedelta(seconds=40))
    assert send(s, e)["accepted"] == [e["event_id"]]
    again = send(s, e, e)  # retry of the whole batch, twice
    assert again["accepted"] == [] and again["duplicate"] == [e["event_id"], e["event_id"]]
    reused = dict(e, recorded_at=(timezone.now() - timedelta(seconds=5)).isoformat())
    r = send(s, reused)
    assert r["rejected"] == [{"event_id": e["event_id"], "reason": "event_id_reused"}]
    assert len(ok(s.ops.get(f"/trips/{trip['id']}/locations"))["points"]) == 1  # stored exactly once


def test_old_and_future_timestamps(s: Setup, trip: dict[str, Any]) -> None:
    now = timezone.now()
    r = send(s, ev(trip, s, at=now - timedelta(days=400)), ev(trip, s, at=now + timedelta(minutes=10)))
    assert sorted(x["reason"] for x in r["rejected"]) == ["future_timestamp", "too_old"]
    skewed = ev(trip, s, at=now + timedelta(minutes=2))  # device clock slightly ahead: kept, not trusted
    r = send(s, skewed)
    assert r["flagged"] == {skewed["event_id"]: ["clock_skew"]}


def test_older_event_never_overwrites_newer(s: Setup, trip: dict[str, Any]) -> None:
    now = timezone.now()
    newer = ev(trip, s, at=now - timedelta(seconds=10), lat=11.60)
    older = ev(trip, s, at=now - timedelta(seconds=90), lat=11.55)
    send(s, newer)
    r = send(s, older)  # arrives later (e.g. an offline queue) but was recorded earlier
    assert r["accepted"] == [older["event_id"]] and r["flagged"] == {older["event_id"]: ["out_of_order"]}
    loc = latest(s)
    assert loc["latitude"] == pytest.approx(11.60)
    assert loc["recorded_at"].startswith((now - timedelta(seconds=10)).isoformat()[:19])
    # Even in one batch the newest trusted point wins, whatever the order inside the batch.
    later, earlier = (
        ev(trip, s, at=now - timedelta(seconds=3), lat=11.6002),
        ev(trip, s, at=now - timedelta(seconds=6), lat=11.6001),
    )
    send(s, later, earlier)
    assert latest(s)["latitude"] == pytest.approx(11.6002)


def test_impossible_speed_is_flagged(s: Setup, trip: dict[str, Any]) -> None:
    now = timezone.now()
    send(s, ev(trip, s, at=now - timedelta(seconds=120)))
    jump = ev(trip, s, at=now - timedelta(seconds=60), lat=DJIBOUTI[0] + 1.0)  # ~111 km in 60 s
    r = send(s, jump)
    assert r["flagged"] == {jump["event_id"]: ["impossible_speed"]}
    assert latest(s)["latitude"] == pytest.approx(DJIBOUTI[0])
    plausible = ev(trip, s, at=now - timedelta(seconds=30), lat=DJIBOUTI[0] + 0.005)  # ~550 m in 90 s
    assert send(s, plausible)["flagged"] == {}


def test_unauthorized_vehicle_driver_or_device(s: Setup, trip: dict[str, Any], world: World) -> None:
    other_vehicle = ok(post(s.fleet, "/vehicles", {"plate": "DJ 9999 X"}), 201)
    r = send(s, ev(trip, s, vehicle=other_vehicle["id"]))
    assert r["rejected"][0]["reason"] == "vehicle_mismatch"
    # Another company's driver (no driver profile linked here): refused outright.
    err(
        client_for(world.m("bravo_driver")).post("/tracking/location/batch", {"events": [ev(trip, s)]}),
        403,
        "forbidden",
    )
    # Office users never ingest; drivers' devices do.
    err(s.ops.post("/tracking/location/batch", {"events": [ev(trip, s)]}), 403, "forbidden")
    # The first accepted upload binds the device; a second phone is refused.
    send(s, ev(trip, s))
    r = send(s, ev(trip, s, device=uuid.uuid4()))
    assert r["rejected"][0]["reason"] == "device_mismatch"
    # tenant_id in the body is not a field at all.
    code, _ = s.driver.post("/tracking/location", {**ev(trip, s), "tenant_id": str(world.tenants["bravo"])})
    assert code == 422


def test_closed_trip_and_late_uploads(s: Setup, trip: dict[str, Any], world: World) -> None:
    during = ev(trip, s, at=timezone.now() - timedelta(seconds=30))
    ok(post(s.driver, f"/trips/{trip['id']}/complete"))
    r = send(s, ev(trip, s, at=timezone.now()))  # recorded after the trip closed
    assert r["rejected"][0]["reason"] == "outside_session_window"
    assert send(s, during)["accepted"] == [during["event_id"]]  # offline queue drained late: accepted
    with tenant_context(world.tenants["alpha"]), connection.cursor() as cur:  # 2 days later...
        cur.execute(
            "UPDATE tracking_sessions SET closed_at = now() - interval '2 days', "
            "opened_at = now() - interval '3 days' WHERE trip_id = %s",
            [trip["id"]],
        )
    late = ev(trip, s, at=timezone.now() - timedelta(days=2, hours=1))
    assert send(s, late)["rejected"][0]["reason"] == "session_closed"


def test_points_from_before_the_trip_started_are_rejected(s: Setup, trip: dict[str, Any]) -> None:
    r = send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=20)))
    assert r["rejected"][0]["reason"] == "outside_session_window"


def test_trip_without_session_rejects_gps(s: Setup) -> None:
    _, t = dispatched(s)  # assigned but not started
    r = send(
        s,
        {
            "event_id": str(uuid.uuid4()),
            "device_id": str(DEVICE),
            "trip_id": t["id"],
            "vehicle_id": s.vehicle_id,
            "latitude": 11.6,
            "longitude": 43.1,
            "recorded_at": timezone.now().isoformat(),
        },
    )
    assert r["rejected"][0]["reason"] == "no_session"


# --------------------------------------------------------------------------- freshness


LIMITS = dict(tracking.DEFAULT_THRESHOLDS)


@pytest.mark.parametrize(
    ("age", "active", "state"),
    [
        (0, True, "live"),
        (120, True, "live"),
        (121, True, "delayed"),
        (600, True, "delayed"),
        (601, True, "stale"),
        (3600, True, "stale"),
        (3601, True, "offline"),
        (5, False, "offline"),
    ],
)
def test_freshness_thresholds(age: int, active: bool, state: str) -> None:
    now = timezone.now()
    assert tracking.freshness(
        now - timedelta(seconds=age), now=now, session_active=active, limits=LIMITS
    ) == (state, age)


def backdate_session(world: World, trip_id: str, minutes: int) -> None:
    with tenant_context(world.tenants["alpha"]), connection.cursor() as cur:
        cur.execute(
            "UPDATE tracking_sessions SET opened_at = now() - make_interval(mins => %s) WHERE trip_id = %s",
            [minutes, trip_id],
        )


def test_stale_location_is_never_shown_as_live(s: Setup, trip: dict[str, Any], world: World) -> None:
    backdate_session(world, trip["id"], 60)
    send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=20)))
    loc = latest(s)
    assert loc["freshness"] == "stale" and loc["age_seconds"] >= 20 * 60
    fleet = ok(s.ops.get("/tracking/fleet"))
    mine = next(v for v in fleet["vehicles"] if v["vehicle_id"] == s.vehicle_id)
    assert mine["freshness"] == "stale" and mine["vehicle_plate"] == "DJ 1001 A"
    ok(post(s.driver, f"/trips/{trip['id']}/complete"))
    assert latest(s)["freshness"] == "offline"  # session closed: offline whatever the age


def test_tenant_thresholds_are_respected(s: Setup, trip: dict[str, Any], world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    ok(admin.patch("/tenant", {"settings": {"freshness_live_seconds": 30}}))
    send(s, ev(trip, s, at=timezone.now() - timedelta(seconds=60)))
    assert latest(s)["freshness"] == "delayed"


# --------------------------------------------------------------------------- isolation & scope


def test_gps_is_isolated_between_tenants(s: Setup, trip: dict[str, Any], world: World) -> None:
    send(s, ev(trip, s))
    bravo = client_for(world.m("bravo_admin"))
    err(bravo.get(f"/trips/{trip['id']}/locations"), 404, "not_found")
    err(bravo.get(f"/vehicles/{s.vehicle_id}/location"), 404, "not_found")
    assert all(v["vehicle_id"] != s.vehicle_id for v in ok(bravo.get("/tracking/fleet"))["vehicles"])
    with tenant_context(world.tenants["bravo"]), connection.cursor() as cur:
        cur.execute("SELECT count(*) FROM gps_location_events WHERE trip_id = %s", [trip["id"]])
        assert cur.fetchone()[0] == 0  # RLS, even with raw SQL
    with connection.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege('corridor_app', 'gps_location_events', 'UPDATE'), "
            "has_table_privilege('corridor_app', 'gps_location_events', 'DELETE')"
        )
        assert cur.fetchone() == (False, False)  # append-only


def test_driver_sees_own_track_customer_sees_none(s: Setup, trip: dict[str, Any], world: World) -> None:
    send(s, ev(trip, s))
    assert len(ok(s.driver.get(f"/trips/{trip['id']}/locations"))["points"]) == 1
    ok(s.driver.get(f"/vehicles/{s.vehicle_id}/location"))
    code, _ = client_for(world.m("alpha_customer")).get(f"/trips/{trip['id']}/locations")
    assert code in (403, 404)


# --------------------------------------------------------------------------- realtime


def test_live_update_reaches_subscribers_within_target(
    s: Setup, trip: dict[str, Any], world: World, django_capture_on_commit_callbacks: Any
) -> None:
    """A stored point is pushed to the tenant's fleet group right after commit (target: ≤ 10 s)."""
    layer = get_channel_layer()
    mine = async_to_sync(layer.new_channel)()
    theirs = async_to_sync(layer.new_channel)()
    async_to_sync(layer.group_add)(fleet_group(world.tenants["alpha"]), mine)
    async_to_sync(layer.group_add)(fleet_group(world.tenants["bravo"]), theirs)
    e = ev(trip, s)
    started = time.monotonic()
    with django_capture_on_commit_callbacks(execute=True):
        send(s, e)
    message = async_to_sync(layer.receive)(mine)
    elapsed = time.monotonic() - started
    assert message["type"] == "fleet.update"
    assert message["payload"]["vehicle_id"] == s.vehicle_id and message["payload"]["recorded_at"]
    assert elapsed < 10.0, elapsed
    print(f"\n[latency] ingest -> fleet group message: {elapsed * 1000:.1f} ms")  # noqa: T201  (evidence)
    # The other tenant's group got nothing.
    import asyncio

    with pytest.raises(asyncio.TimeoutError):
        async_to_sync(asyncio.wait_for)(layer.receive(theirs), 0.2)


def test_untrusted_points_are_not_broadcast(
    s: Setup, trip: dict[str, Any], world: World, django_capture_on_commit_callbacks: Any
) -> None:
    send(s, ev(trip, s, at=timezone.now() - timedelta(seconds=5)))
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        send(s, ev(trip, s, at=timezone.now() - timedelta(seconds=60)))  # out of order
    assert callbacks == []


# --------------------------------------------------------------------------- partitions & retention


@pytest.mark.django_db(databases=["default", "relay"])
def test_partitions_cover_the_accepted_window() -> None:
    def names() -> list[str]:
        with connections["relay"].cursor() as cur:
            cur.execute("SELECT name FROM gps_partitions()")
            return [r[0] for r in cur.fetchall()]

    got = in_thread(names)
    now = timezone.now()
    current = f"gps_location_events_y{now:%Y}m{now:%m}"
    assert current in got and len(got) >= 15  # 12+ months back, current, months ahead


@pytest.mark.django_db(databases=["default", "relay"])
def test_retention_archives_then_drops_only_with_approval(world: World, tmp_path: Any, settings: Any) -> None:
    from corridor.tracking.tasks import run_maintenance

    settings.GPS_ARCHIVE_DIR = str(tmp_path)
    settings.GPS_ARCHIVE_BACKEND = "local"
    old = (timezone.now().replace(day=15) - timedelta(days=30 * 15)).replace(day=10)
    name = f"gps_location_events_y{old:%Y}m{old:%m}"

    def seed() -> None:
        with connections["relay"].cursor() as cur:
            cur.execute("SELECT gps_create_month_partition(%s)", [old.date()])
        with tenant_context(world.tenants["alpha"]), connection.cursor() as cur:
            cur.execute(
                "INSERT INTO gps_location_events (tenant_id, event_id, device_id, session_id, trip_id, vehicle_id, "
                "driver_id, point, recorded_at, source) VALUES (%s, %s, %s, %s, %s, %s, %s, "
                "ST_SetSRID(ST_MakePoint(43.1, 11.6), 4326), %s, 'phone_gps')",
                [
                    world.tenants["alpha"],
                    uuid.uuid4(),
                    DEVICE,
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                    uuid.uuid4(),
                    old,
                ],
            )

    def partitions() -> list[str]:
        with connections["relay"].cursor() as cur:
            cur.execute("SELECT name FROM gps_partitions()")
            return [r[0] for r in cur.fetchall()]

    in_thread(seed)
    report = in_thread(lambda: run_maintenance(drop_enabled=False))
    assert name in report.archived and name in report.pending_approval and not report.dropped
    assert name in in_thread(partitions)  # nothing deleted without approval
    manifest = (tmp_path / f"{name}.manifest.json").read_text(encoding="utf-8")
    assert '"rows": 1' in manifest

    report = in_thread(lambda: run_maintenance(drop_enabled=True))
    assert report.dropped == [name] and not report.failed
    assert name not in in_thread(partitions)

    def drop_current() -> str:
        now = timezone.now()
        try:
            with connections["relay"].cursor() as cur:
                cur.execute("SELECT gps_drop_partition(%s, 12)", [f"gps_location_events_y{now:%Y}m{now:%m}"])
        except Exception as exc:
            return str(exc)
        return "dropped"

    assert "inside the retention window" in in_thread(drop_current)


@pytest.mark.django_db(databases=["default", "relay"])
def test_maintenance_role_cannot_read_gps_directly() -> None:
    def probe() -> Any:
        with connections["relay"].cursor() as cur:
            cur.execute(
                "SELECT has_table_privilege(current_user, 'gps_location_events', 'SELECT'), "
                "has_table_privilege(current_user, 'tracking_sessions', 'SELECT')"
            )
            return cur.fetchone()

    assert in_thread(probe) == (False, False)
