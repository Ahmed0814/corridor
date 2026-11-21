"""Phase 3: core logistics end to end through the API, as the real application role.

Covers MASTER_PROMPT §8 "Lifecycle": valid and invalid transitions, unauthorized dispatch, duplicate
dispatch, conflicting vehicle/driver assignment, invalid (premature) delivery, completed-trip
correction, plus scope rules, cross-tenant isolation, idempotency, PII protection and the outbox.
The concurrent dispatch race lives in test_dispatch_race.py.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest

from corridor.containers.services import iso6346_valid
from corridor.core.tenancy import tenant_context
from corridor.events.models import OutboxEvent
from tests.support import ApiClient, World, client_for

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- helpers


def post(c: ApiClient, path: str, body: Any = None, key: str | None = None) -> tuple[int, Any]:
    return c.post(
        path, body if body is not None else {}, headers={"Idempotency-Key": key or uuid.uuid4().hex}
    )


def patch(c: ApiClient, path: str, body: Any) -> tuple[int, Any]:
    return c.patch(path, body, headers={"Idempotency-Key": uuid.uuid4().hex})


def container_number(serial: int, owner: str = "TSTU") -> str:
    base = f"{owner}{serial:06d}"
    for digit in range(10):
        if iso6346_valid(f"{base}{digit}"):
            return f"{base}{digit}"
    raise AssertionError("unreachable: every serial has exactly one check digit")


def ok(result: tuple[int, Any], status: int = 200) -> Any:
    code, body = result
    assert code == status, body
    return body


def err(result: tuple[int, Any], status: int, code: str) -> Any:
    got, body = result
    assert got == status, body
    assert body["error"]["code"] == code, body
    return body


@dataclass
class Setup:
    ops: ApiClient  # ops manager: shipments, dispatch, clearance, delivery, on-behalf
    disp: ApiClient  # dispatcher
    fleet: ApiClient  # fleet manager: vehicles, drivers, PII
    driver: ApiClient  # the alpha driver (driver-mobile client)
    customer_id: str
    container_id: str
    vehicle_id: str
    driver_id: str


@pytest.fixture
def s(world: World) -> Setup:
    ops = client_for(world.m("alpha_ops_manager"))
    fleet = client_for(world.m("alpha_fleet_manager"))
    customer = ok(post(ops, "/customers", {"name": "TEST Customer One"}), 201)
    container = ok(post(ops, "/containers", {"number": container_number(1001), "size_ft": 40}), 201)
    vehicle = ok(post(fleet, "/vehicles", {"plate": "dj 1001 a"}), 201)
    driver = ok(post(fleet, "/drivers", {"full_name": "TEST Driver", "license_number": "et-123 456"}), 201)
    ok(
        post(
            fleet,
            f"/drivers/{driver['id']}/link",
            {"membership_id": str(world.m("alpha_driver").membership_id)},
        )
    )
    return Setup(
        ops=ops,
        disp=client_for(world.m("alpha_dispatcher")),
        fleet=fleet,
        driver=client_for(world.m("alpha_driver")),
        customer_id=customer["id"],
        container_id=container["id"],
        vehicle_id=vehicle["id"],
        driver_id=driver["id"],
    )


def new_shipment(s: Setup, containers: list[str] | None = None) -> dict[str, Any]:
    created: dict[str, Any] = ok(
        post(
            s.ops,
            "/shipments",
            {
                "customer_id": s.customer_id,
                "origin_label": "Port of Djibouti",
                "destination_label": "Addis Ababa",
                "container_ids": containers if containers is not None else [s.container_id],
                "weight_kg": 21500.5,
                "origin": {"lat": 11.6, "lng": 43.1},
            },
        ),
        201,
    )
    return created


def dispatched(s: Setup) -> tuple[dict[str, Any], dict[str, Any]]:
    """A confirmed shipment on an assigned trip, dispatched. Returns (shipment, trip)."""
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    trip = ok(
        post(
            s.ops,
            "/trips",
            {"origin_label": "Djibouti", "destination_label": "Addis Ababa", "shipment_ids": [sh["id"]]},
        ),
        201,
    )
    ok(post(s.ops, f"/trips/{trip['id']}/assign", {"vehicle_id": s.vehicle_id, "driver_id": s.driver_id}))
    sh = ok(post(s.ops, f"/shipments/{sh['id']}/dispatch"))
    return sh, trip


# --------------------------------------------------------------------------- reference data


def test_iso6346_check_digit() -> None:
    assert iso6346_valid("CSQU3054383")  # the standard's published example
    assert not iso6346_valid("CSQU3054384")  # wrong check digit
    assert not iso6346_valid("CSQX3054383")  # category must be U, J or Z
    assert not iso6346_valid("CSQU305438")  # too short


def test_container_number_is_validated_and_normalised(s: Setup) -> None:
    err(post(s.ops, "/containers", {"number": "CSQU3054384", "size_ft": 20}), 422, "validation_error")
    c = ok(post(s.ops, "/containers", {"number": "csqu 305438-3", "size_ft": 20}), 201)
    assert c["number"] == "CSQU3054383"
    err(post(s.ops, "/containers", {"number": "CSQU3054383", "size_ft": 20}), 409, "conflict")


def test_driver_license_is_encrypted_and_pii_is_protected(s: Setup, world: World) -> None:
    from django.db import connection

    from corridor.core import crypto

    assert ok(s.fleet.get(f"/drivers/{s.driver_id}"))["license_number"] == "ET-123456"  # drivers.pii
    as_dispatcher = ok(s.disp.get(f"/drivers/{s.driver_id}"))
    assert as_dispatcher["license_number"] is None and as_dispatcher["phone_e164"] is None
    own = ok(s.driver.get("/drivers/me"))  # a driver always sees their own data
    assert own["id"] == s.driver_id and own["license_number"] == "ET-123456"

    with tenant_context(world.tenants["alpha"]), connection.cursor() as cur:
        cur.execute(
            "SELECT license_number_enc, license_number_hash FROM drivers WHERE id = %s", [s.driver_id]
        )
        stored, digest = cur.fetchone()
    assert "ET-123456" not in stored and "123456" not in stored  # encrypted at rest
    assert crypto.decrypt(stored) == "ET-123456"
    assert digest == crypto.lookup_hash("et 123456")  # normalised keyed hash for uniqueness
    # Duplicate license numbers are refused without decrypting anything.
    err(post(s.fleet, "/drivers", {"full_name": "TEST Dup", "license_number": "ET123456"}), 409, "conflict")


# --------------------------------------------------------------------------- happy path


def test_full_lifecycle_end_to_end(s: Setup, world: World) -> None:
    sh, trip = dispatched(s)
    assert sh["status"] == "dispatched"
    assert ok(s.ops.get(f"/containers/{s.container_id}"))["availability"] == "in_use"
    assert ok(s.fleet.get(f"/vehicles/{s.vehicle_id}"))["assigned_trip_id"] == trip["id"]

    # The driver starts their own trip: the shipment moves to in_transit (system transition).
    trip = ok(post(s.driver, f"/trips/{trip['id']}/start"))
    assert trip["status"] == "in_progress"
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "in_transit"

    # Border arrival is not clearance; only an authorized operator clears (hard rule 8).
    assert (
        ok(post(s.disp, f"/shipments/{sh['id']}/border-arrival", {"border": "Galafi"}))["status"]
        == "at_border"
    )
    err(post(s.disp, f"/shipments/{sh['id']}/border-clearance", {"border": "Galafi"}), 403, "forbidden")
    assert (
        ok(post(s.ops, f"/shipments/{sh['id']}/border-clearance", {"border": "Galafi"}))["status"]
        == "in_transit"
    )

    ok(post(s.driver, f"/trips/{trip['id']}/pause"))
    ok(post(s.driver, f"/trips/{trip['id']}/resume"))
    delivered = ok(post(s.driver, f"/shipments/{sh['id']}/deliver", {"recipient_name": "TEST Recipient"}))
    assert delivered["status"] == "delivered" and delivered["delivered_at"] is not None
    assert ok(s.ops.get(f"/containers/{s.container_id}"))["availability"] == "available"

    done = ok(post(s.driver, f"/trips/{trip['id']}/complete"))
    assert done["status"] == "completed" and done["assignment"] is None
    assert ok(s.fleet.get(f"/vehicles/{s.vehicle_id}"))["assigned_trip_id"] is None

    history = [
        (e["type"], e["from_status"], e["to_status"]) for e in ok(s.ops.get(f"/shipments/{sh['id']}/events"))
    ]
    assert history == [
        ("created", "", "draft"),
        ("confirmed", "draft", "confirmed"),
        ("dispatched", "confirmed", "dispatched"),
        ("in_transit", "dispatched", "in_transit"),
        ("border_arrived", "in_transit", "at_border"),
        ("border_cleared", "at_border", "in_transit"),
        ("delivered", "in_transit", "delivered"),
    ]
    trip_history = [e["type"] for e in ok(s.ops.get(f"/trips/{trip['id']}/events"))]
    assert trip_history == ["created", "assigned", "started", "paused", "resumed", "completed"]

    # Business events were written to the outbox in the same transactions.
    with tenant_context(world.tenants["alpha"]):
        types = list(
            OutboxEvent.objects.filter(aggregate_id__in=[sh["id"], trip["id"]])
            .order_by("id")
            .values_list("type", flat=True)
        )
    assert types == [
        "shipment.created",
        "shipment.confirmed",
        "trip.created",
        "trip.assigned",
        "shipment.dispatched",
        "trip.started",
        "border.arrived",
        "border.clearance.confirmed",
        "shipment.delivered",
        "trip.completed",
    ]


def test_one_step_dispatch_endpoint(s: Setup) -> None:
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    trip = ok(
        post(
            s.ops,
            "/dispatch",
            {
                "shipment_ids": [sh["id"]],
                "vehicle_id": s.vehicle_id,
                "driver_id": s.driver_id,
                "origin_label": "Djibouti",
                "destination_label": "Dire Dawa",
            },
        ),
        201,
    )
    assert trip["status"] == "assigned" and trip["assignment"]["driver_id"] == s.driver_id
    assert ok(s.ops.get(f"/shipments/{sh['id']}"))["status"] == "dispatched"


def test_one_step_dispatch_is_all_or_nothing(s: Setup) -> None:
    draft = new_shipment(s)  # not confirmed: dispatch must fail and leave no trip behind
    before = ok(s.ops.get("/trips"))["items"]
    err(
        post(
            s.ops,
            "/dispatch",
            {
                "shipment_ids": [draft["id"]],
                "vehicle_id": s.vehicle_id,
                "driver_id": s.driver_id,
                "origin_label": "A",
                "destination_label": "B",
            },
        ),
        409,
        "shipment_not_plannable",
    )
    assert ok(s.ops.get("/trips"))["items"] == before
    assert ok(s.fleet.get(f"/vehicles/{s.vehicle_id}"))["assigned_trip_id"] is None


# --------------------------------------------------------------------------- invalid transitions


def test_invalid_transitions_are_rejected(s: Setup) -> None:
    sh = new_shipment(s)
    err(post(s.ops, f"/shipments/{sh['id']}/dispatch"), 409, "invalid_transition")  # draft
    err(post(s.ops, f"/shipments/{sh['id']}/deliver", {"recipient_name": "x"}), 409, "invalid_transition")
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    err(post(s.ops, f"/shipments/{sh['id']}/confirm"), 409, "invalid_transition")  # twice
    body = err(
        post(s.ops, f"/shipments/{sh['id']}/deliver", {"recipient_name": "x"}), 409, "invalid_transition"
    )
    assert body["error"]["details"]["status"] == "confirmed"  # premature delivery
    err(post(s.ops, f"/shipments/{sh['id']}/dispatch"), 409, "no_assigned_trip")  # no trip yet
    err(patch(s.ops, f"/shipments/{sh['id']}", {"cargo_description": "x"}), 409, "invalid_transition")


def test_duplicate_dispatch_is_rejected(s: Setup) -> None:
    sh, _ = dispatched(s)
    err(post(s.ops, f"/shipments/{sh['id']}/dispatch"), 409, "invalid_transition")


def test_unauthorized_dispatch(s: Setup, world: World) -> None:
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    for key in ("alpha_fleet_manager", "alpha_customer"):
        code, body = post(client_for(world.m(key)), f"/shipments/{sh['id']}/dispatch")
        assert code in (403, 404), body
    code, _ = post(s.driver, f"/shipments/{sh['id']}/dispatch")
    assert code in (403, 404)


def test_trip_cannot_start_before_assignment_or_dispatch(s: Setup) -> None:
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    trip = ok(
        post(s.ops, "/trips", {"origin_label": "A", "destination_label": "B", "shipment_ids": [sh["id"]]}),
        201,
    )
    err(post(s.ops, f"/trips/{trip['id']}/start", {"reason": "x"}), 409, "invalid_transition")
    ok(post(s.ops, f"/trips/{trip['id']}/assign", {"vehicle_id": s.vehicle_id, "driver_id": s.driver_id}))
    err(post(s.driver, f"/trips/{trip['id']}/start"), 409, "shipments_not_dispatched")


def test_only_the_assigned_driver_or_an_office_user_with_a_reason_starts(s: Setup, world: World) -> None:
    _, trip = dispatched(s)
    # Another company's driver cannot even see the trip.
    err(post(client_for(world.m("bravo_driver")), f"/trips/{trip['id']}/start"), 404, "not_found")
    # The dispatcher may act on behalf of the driver, but only with a reason.
    err(post(s.disp, f"/trips/{trip['id']}/start"), 422, "reason_required")
    started = ok(post(s.disp, f"/trips/{trip['id']}/start", {"reason": "Driver phone broken"}))
    assert started["status"] == "in_progress"
    events = ok(s.ops.get(f"/trips/{trip['id']}/events"))
    assert events[-1]["reason"] == "Driver phone broken"


def test_conflicting_assignments_are_rejected(s: Setup) -> None:
    _, trip1 = dispatched(s)
    sh2 = new_shipment(s, containers=[])
    ok(post(s.ops, f"/shipments/{sh2['id']}/confirm"))
    trip2 = ok(
        post(s.ops, "/trips", {"origin_label": "A", "destination_label": "B", "shipment_ids": [sh2["id"]]}),
        201,
    )
    # Same driver and vehicle while trip1 holds them.
    err(
        post(s.ops, f"/trips/{trip2['id']}/assign", {"vehicle_id": s.vehicle_id, "driver_id": s.driver_id}),
        409,
        "assignment_conflict",
    )
    # A vehicle in maintenance cannot be assigned; an assigned vehicle cannot go to maintenance.
    v2 = ok(post(s.fleet, "/vehicles", {"plate": "DJ 2002 B"}), 201)
    ok(post(s.fleet, f"/vehicles/{v2['id']}/status", {"status": "maintenance"}))
    err(
        post(s.ops, f"/trips/{trip2['id']}/assign", {"vehicle_id": v2["id"], "driver_id": s.driver_id}),
        409,
        "vehicle_unavailable",
    )
    err(post(s.fleet, f"/vehicles/{s.vehicle_id}/status", {"status": "maintenance"}), 409, "vehicle_assigned")
    assert trip1["status"] == "planned"  # snapshot from creation; the live trip is assigned


def test_container_cannot_be_on_two_active_shipments(s: Setup) -> None:
    new_shipment(s)
    err(
        post(
            s.ops,
            "/shipments",
            {
                "customer_id": s.customer_id,
                "origin_label": "A",
                "destination_label": "B",
                "container_ids": [s.container_id],
            },
        ),
        409,
        "container_unavailable",
    )


def test_cancel_releases_containers(s: Setup) -> None:
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    assert ok(s.ops.get(f"/containers/{s.container_id}"))["availability"] == "in_use"
    err(post(s.ops, f"/shipments/{sh['id']}/cancel", {"reason": ""}), 422, "validation_error")
    ok(post(s.ops, f"/shipments/{sh['id']}/cancel", {"reason": "Customer withdrew"}))
    assert ok(s.ops.get(f"/containers/{s.container_id}"))["availability"] == "available"


def test_failed_delivery_and_reattempt(s: Setup) -> None:
    sh, trip = dispatched(s)
    ok(post(s.driver, f"/trips/{trip['id']}/start"))
    assert (
        ok(post(s.driver, f"/shipments/{sh['id']}/delivery-failed", {"reason": "Gate closed"}))["status"]
        == "delivery_failed"
    )
    err(post(s.driver, f"/shipments/{sh['id']}/deliver", {"recipient_name": "x"}), 409, "invalid_transition")
    assert ok(post(s.ops, f"/shipments/{sh['id']}/reattempt"))["status"] == "in_transit"


def test_delay_is_a_flag_with_an_event(s: Setup, world: World) -> None:
    sh = new_shipment(s)
    ok(post(s.ops, f"/shipments/{sh['id']}/confirm"))
    marked = ok(post(s.ops, f"/shipments/{sh['id']}/delay", {"reason": "Port congestion"}))
    assert marked["is_delayed"] and marked["status"] == "confirmed"
    with tenant_context(world.tenants["alpha"]):
        assert OutboxEvent.objects.filter(aggregate_id=sh["id"], type="shipment.delayed").count() == 1


# --------------------------------------------------------------------------- corrections


def test_completed_trip_correction_needs_permission_and_reason(s: Setup, world: World) -> None:
    sh, trip = dispatched(s)
    ok(post(s.driver, f"/trips/{trip['id']}/start"))
    ok(post(s.driver, f"/shipments/{sh['id']}/deliver", {"recipient_name": "TEST Recipient"}))
    ok(post(s.driver, f"/trips/{trip['id']}/complete"))
    err(
        post(s.disp, f"/trips/{trip['id']}/corrections", {"to_status": "in_progress", "reason": "x"}),
        403,
        "forbidden",
    )
    admin = client_for(world.m("alpha_admin"))
    # Reopening needs an active assignment; correcting the record to "aborted" does not.
    err(
        post(
            admin, f"/trips/{trip['id']}/corrections", {"to_status": "in_progress", "reason": "Ended early"}
        ),
        409,
        "no_active_assignment",
    )
    corrected = ok(
        post(
            admin,
            f"/trips/{trip['id']}/corrections",
            {"to_status": "aborted", "reason": "Completed by mistake; trip was abandoned"},
        )
    )
    assert corrected["status"] == "aborted"
    events = ok(s.ops.get(f"/trips/{trip['id']}/events"))
    assert [e["type"] for e in events][-2:] == ["completed", "correction"]  # history kept, not rewritten
    assert events[-1]["reason"].startswith("Completed by mistake")
    assert events[-1]["payload"]["corrected_from"] == "completed"
    # Delivered shipment can be reopened by an authorized correction, recorded as a new event.
    reopened = ok(
        post(
            admin,
            f"/shipments/{sh['id']}/corrections",
            {"to_status": "in_transit", "reason": "Delivered to the wrong consignee"},
        )
    )
    assert reopened["status"] == "in_transit" and reopened["delivered_at"] is None
    sh_events = ok(s.ops.get(f"/shipments/{sh['id']}/events"))
    assert [e["type"] for e in sh_events][-2:] == ["delivered", "correction"]


# --------------------------------------------------------------------------- isolation & scope


def test_other_tenants_get_404_for_every_resource(s: Setup, world: World) -> None:
    sh, trip = dispatched(s)
    bravo = client_for(world.m("bravo_admin"))
    for path in (
        f"/customers/{s.customer_id}",
        f"/containers/{s.container_id}",
        f"/vehicles/{s.vehicle_id}",
        f"/drivers/{s.driver_id}",
        f"/shipments/{sh['id']}",
        f"/trips/{trip['id']}",
        f"/shipments/{sh['id']}/events",
        f"/trips/{trip['id']}/events",
    ):
        err(bravo.get(path), 404, "not_found")
    for path, body in (
        (f"/shipments/{sh['id']}/cancel", {"reason": "x"}),
        (f"/trips/{trip['id']}/start", {"reason": "x"}),
        (f"/vehicles/{s.vehicle_id}/status", {"status": "maintenance"}),
    ):
        err(post(bravo, path, body), 404, "not_found")
    # Lists never leak another tenant's rows.
    assert all(x["id"] != sh["id"] for x in ok(bravo.get("/shipments"))["items"])
    # Referencing another tenant's ids when creating is also a 404/409, never a cross-tenant link.
    code, _ = post(
        bravo, "/shipments", {"customer_id": s.customer_id, "origin_label": "A", "destination_label": "B"}
    )
    assert code == 409


def test_tenant_id_in_a_body_is_rejected(s: Setup, world: World) -> None:
    err(
        post(s.ops, "/customers", {"name": "x", "tenant_id": str(world.tenants["bravo"])}),
        422,
        "validation_error",
    )


def test_customer_sees_only_their_own_shipments(s: Setup, world: World) -> None:
    from corridor.identity import services as identity

    mine = new_shipment(s, containers=[])
    other_customer = ok(post(s.ops, "/customers", {"name": "TEST Customer Two"}), 201)
    theirs = ok(
        post(
            s.ops,
            "/shipments",
            {"customer_id": other_customer["id"], "origin_label": "A", "destination_label": "B"},
        ),
        201,
    )
    member = world.m("alpha_customer")
    with tenant_context(world.tenants["alpha"]):
        identity.attach_customer_profile(member.membership_id, uuid.UUID(s.customer_id))
    portal = client_for(member)
    assert [x["id"] for x in ok(portal.get("/shipments"))["items"]] == [mine["id"]]
    ok(portal.get(f"/shipments/{mine['id']}"))
    err(portal.get(f"/shipments/{theirs['id']}"), 404, "not_found")
    err(portal.get(f"/customers/{other_customer['id']}"), 404, "not_found")
    assert ok(portal.get("/trips"))["items"] == []  # customers never see trips or drivers
    code, _ = post(
        portal, "/shipments", {"customer_id": s.customer_id, "origin_label": "A", "destination_label": "B"}
    )
    assert code in (403, 404)


def test_driver_sees_only_their_assignments(s: Setup, world: World) -> None:
    _, trip = dispatched(s)
    assert [t["id"] for t in ok(s.driver.get("/trips"))["items"]] == [trip["id"]]
    other = new_shipment(s, containers=[])
    err(s.driver.get(f"/shipments/{other['id']}"), 404, "not_found")
    assert ok(s.driver.get("/drivers"))["items"][0]["id"] == s.driver_id
    assert len(ok(s.driver.get("/drivers"))["items"]) == 1


# --------------------------------------------------------------------------- idempotency


def test_idempotency_key_replays_and_detects_reuse(s: Setup) -> None:
    key = uuid.uuid4().hex
    first = ok(post(s.ops, "/customers", {"name": "TEST Idem"}, key=key), 201)
    again = ok(post(s.ops, "/customers", {"name": "TEST Idem"}, key=key), 201)
    assert again == first  # replayed, not created twice
    names = [
        c["name"]
        for c in ok(
            s.ops.get(
                "/customers",
            )
        )["items"]
    ]
    assert names.count("TEST Idem") == 1
    err(post(s.ops, "/customers", {"name": "TEST Different"}, key=key), 422, "idempotency_key_reused")
    code, body = s.ops.post("/customers", {"name": "TEST NoKey"})
    assert code == 400 and body["error"]["code"] == "idempotency_key_required"


def test_idempotent_transition_is_not_applied_twice(s: Setup) -> None:
    sh = new_shipment(s)
    key = uuid.uuid4().hex
    first = ok(post(s.ops, f"/shipments/{sh['id']}/confirm", key=key))
    second = ok(post(s.ops, f"/shipments/{sh['id']}/confirm", key=key))  # replay, not a 409
    assert first == second
    assert [e["type"] for e in ok(s.ops.get(f"/shipments/{sh['id']}/events"))].count("confirmed") == 1
