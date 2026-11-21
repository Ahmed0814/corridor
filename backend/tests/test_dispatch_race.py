"""Concurrency: the concurrent dispatch race and the outbox relay, with real commits.

These tests need data that other database connections can see, so their setup is committed (in a
worker thread, outside the test's rollback transaction). Rows are TEST data in the test database
only (hard rule 7) and use unique references so other tests are unaffected.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connections

from corridor.core.api import ApiError
from corridor.core.tenancy import tenant_context
from corridor.identity.permissions import ROLES, ClientKind, Scope
from corridor.identity.schemas import RequestContext
from tests.support import World

pytestmark = pytest.mark.django_db


def in_thread[T](fn: Callable[[], T]) -> T:
    """Run fn on its own DB connection (autocommit outside atomic) and return its result."""
    out: dict[str, Any] = {}

    def run() -> None:
        try:
            out["value"] = fn()
        except BaseException as exc:  # re-raised in the caller
            out["error"] = exc
        finally:
            connections.close_all()

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=60)
    if "error" in out:
        raise out["error"]
    return out["value"]  # type: ignore[no-any-return]


def office_ctx(world: World, role: str = "dispatcher") -> RequestContext:
    m = world.m("alpha_dispatcher")
    return RequestContext(
        user_id=m.user_id,
        user_sub=m.sub,
        client_kind=ClientKind.WEB_OFFICE,
        is_platform_admin=False,
        mfa_verified=True,
        tenant_id=world.tenants["alpha"],
        tenant_slug="alpha",
        membership_id=m.membership_id,
        role=role,
        scope=Scope.TENANT,
        permissions=ROLES[role].permissions,
    )


def test_concurrent_dispatch_race_has_exactly_one_winner(world: World) -> None:
    """Two dispatchers assign the same driver to two different trips at the same moment.
    Exactly one wins; the other gets 409 assignment_conflict; the driver ends with one active trip."""
    from corridor.customers import services as customers
    from corridor.customers.schemas import CustomerIn
    from corridor.drivers import services as drivers
    from corridor.drivers.schemas import DriverIn
    from corridor.fleet import services as fleet
    from corridor.fleet.schemas import VehicleIn
    from corridor.shipments import services as shipments
    from corridor.shipments.schemas import ShipmentIn
    from corridor.trips import services as trips
    from corridor.trips.schemas import AssignIn, TripIn

    ctx = office_ctx(world)
    tag = uuid.uuid4().hex[:6].upper()

    def setup() -> dict[str, Any]:
        with tenant_context(ctx.tenant_id, user_id=ctx.user_id):
            customer = customers.create_customer(ctx, CustomerIn(name=f"TEST Race {tag}"))
            driver = drivers.create_driver(ctx, DriverIn(full_name=f"TEST Race Driver {tag}"))
            v1 = fleet.create_vehicle(ctx, VehicleIn(plate=f"RACE {tag} 1"))
            v2 = fleet.create_vehicle(ctx, VehicleIn(plate=f"RACE {tag} 2"))
            trip_ids = []
            for i in (1, 2):
                sh = shipments.create_shipment(
                    ctx,
                    ShipmentIn(
                        customer_id=customer.id,
                        origin_label="A",
                        destination_label="B",
                        reference=f"RACE-{tag}-{i}",
                    ),
                )
                shipments.confirm_shipment(ctx, sh.id)
                trip_ids.append(
                    trips.create_trip(
                        ctx, TripIn(origin_label="A", destination_label="B", shipment_ids=[sh.id])
                    ).id
                )
            return {"driver": driver.id, "vehicles": [v1.id, v2.id], "trips": trip_ids}

    data = in_thread(setup)
    barrier = threading.Barrier(2)
    results: list[Any] = [None, None]

    def contender(i: int) -> None:
        try:
            with tenant_context(ctx.tenant_id, user_id=ctx.user_id):
                barrier.wait(timeout=10)  # both transactions are open before either assigns
                trips.assign_trip(
                    ctx, data["trips"][i], AssignIn(vehicle_id=data["vehicles"][i], driver_id=data["driver"])
                )
            results[i] = "ok"
        except ApiError as exc:
            results[i] = exc.code
        except BaseException as exc:
            results[i] = repr(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=contender, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert sorted(results) == ["assignment_conflict", "ok"], results

    def check() -> list[str]:
        with tenant_context(ctx.tenant_id, user_id=ctx.user_id):
            return [trips.get_trip(ctx, tid).status for tid in data["trips"]]

    assert sorted(in_thread(check)) == ["assigned", "planned"]


@pytest.mark.django_db(databases=["default", "relay"])
def test_outbox_relay_publishes_committed_events_once(world: World) -> None:
    """The relay (role corridor_relay) sees committed outbox rows of every tenant, publishes each
    exactly once, and never sees rows of transactions that rolled back."""
    from corridor.events import services as events
    from corridor.events.tasks import relay_once

    tag = uuid.uuid4().hex

    def emit_committed() -> int:
        with tenant_context(world.tenants["alpha"]):
            return events.emit(
                "shipment.created", aggregate_type="shipment", aggregate_id=tag, payload={"t": tag}
            )

    def emit_rolled_back() -> None:
        class Boom(Exception):
            pass

        try:
            with tenant_context(world.tenants["bravo"]):
                events.emit(
                    "shipment.created", aggregate_type="shipment", aggregate_id=tag + "-rb", payload={}
                )
                raise Boom
        except Boom:
            pass

    committed_id = in_thread(emit_committed)
    in_thread(emit_rolled_back)

    published = in_thread(relay_once)
    assert published >= 1

    def state() -> list[tuple[Any, ...]]:
        with connections["relay"].cursor() as cur:
            cur.execute(
                "SELECT id, published_at IS NOT NULL, attempts FROM outbox_events WHERE aggregate_id LIKE %s",
                [tag + "%"],
            )
            return list(cur.fetchall())

    rows = in_thread(state)
    assert rows == [(committed_id, True, 1)]  # published once; the rolled-back event never existed
    in_thread(relay_once)  # a second relay run must not publish it again
    assert in_thread(state) == [(committed_id, True, 1)]


@pytest.mark.django_db(databases=["default", "relay"])
def test_relay_role_sees_only_the_outbox(world: World) -> None:
    def probe() -> dict[str, Any]:
        out: dict[str, Any] = {}
        with connections["relay"].cursor() as cur:
            for table in ("shipments", "customers", "tenant_memberships", "audit_logs"):
                cur.execute("SELECT has_table_privilege(current_user, %s, 'SELECT')", [table])
                out[table] = cur.fetchone()[0]
            cur.execute("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user")
            out["role"] = cur.fetchone()
            cur.execute("SELECT has_table_privilege(current_user, 'outbox_events', 'DELETE')")
            out["outbox_delete"] = cur.fetchone()[0]
        return out

    got = in_thread(probe)
    assert got["role"] == (False, False)
    assert not any(got[t] for t in ("shipments", "customers", "tenant_memberships", "audit_logs"))
    assert got["outbox_delete"] is False
