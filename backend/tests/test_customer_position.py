"""Customer view of a shipment's position: approximate, only their own shipment, only while it is on
the road, and only from the trip that carries it (never where the truck was on an earlier job).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from corridor.core.tenancy import tenant_context
from corridor.identity import services as identity
from tests.support import World, client_for
from tests.test_logistics import Setup, deliver, dispatched, err, new_shipment, ok, post, s  # noqa: F401
from tests.test_tracking import backdate_session, ev, send

pytestmark = pytest.mark.django_db


def portal(s: Setup, world: World) -> Any:
    member = world.m("alpha_customer")
    with tenant_context(world.tenants["alpha"]):
        identity.attach_customer_profile(member.membership_id, uuid.UUID(s.customer_id))
    return client_for(member)


def test_customer_sees_rounded_position_of_own_moving_shipment(s: Setup, world: World) -> None:
    sh, t = dispatched(s)
    c = portal(s, world)
    assert ok(c.get(f"/shipments/{sh['id']}/position"))["position"] is None  # not on the road yet

    trip = ok(post(s.driver, f"/trips/{t['id']}/start"))
    backdate_session(world, trip["id"], 30)
    send(s, ev(trip, s, at=timezone.now() - timedelta(minutes=1), lat=11.59412, lng=43.14876))

    pos = ok(c.get(f"/shipments/{sh['id']}/position"))["position"]
    assert pos["latitude"] == 11.59 and pos["longitude"] == 43.15 and pos["precision_km"] == 1.0
    assert {"recorded_at", "received_at", "freshness"} <= set(pos)
    flat = str(pos)
    for secret in (s.driver_id, s.vehicle_id, "plate", "driver"):
        assert secret not in flat

    ok(deliver(s.driver, sh["id"]))
    assert ok(c.get(f"/shipments/{sh['id']}/position"))["position"] is None  # delivered: nothing shown


def test_customer_cannot_see_other_shipments_or_tenants(s: Setup, world: World) -> None:
    c = portal(s, world)
    other_customer = ok(post(s.ops, "/customers", {"name": "TEST Customer Two"}), 201)
    theirs = ok(
        post(
            s.ops,
            "/shipments",
            {"customer_id": other_customer["id"], "origin_label": "A", "destination_label": "B"},
        ),
        201,
    )
    err(c.get(f"/shipments/{theirs['id']}/position"), 404, "not_found")
    mine = new_shipment(s, containers=[])
    err(client_for(world.m("bravo_admin")).get(f"/shipments/{mine['id']}/position"), 404, "not_found")


def test_position_from_an_earlier_trip_is_never_shown(s: Setup, world: World) -> None:
    """The truck's latest point belongs to its previous job: the new shipment shows nothing."""
    first, t1 = dispatched(s)
    trip1 = ok(post(s.driver, f"/trips/{t1['id']}/start"))
    backdate_session(world, trip1["id"], 30)
    send(s, ev(trip1, s, at=timezone.now() - timedelta(minutes=5), lat=11.6, lng=43.1))
    ok(deliver(s.driver, first["id"]))
    ok(post(s.driver, f"/trips/{t1['id']}/complete"))

    second, t2 = dispatched(s)
    ok(post(s.driver, f"/trips/{t2['id']}/start"))  # started, but no point sent on this trip yet
    c = portal(s, world)
    assert ok(c.get(f"/shipments/{second['id']}/position"))["position"] is None
