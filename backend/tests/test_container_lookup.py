"""Tracking by container number (D-075): office search, customer portal search (own containers only),
and the public lookup that needs the container number AND the shipment reference.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from corridor.core import ratelimit
from corridor.core.tenancy import tenant_context
from corridor.identity import services as identity
from tests.support import ApiClient, World, client_for
from tests.test_logistics import Setup, container_number, dispatched, err, new_shipment, ok, post, s  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public limit is tested on its own; other tests must not depend on Redis counters."""
    monkeypatch.setattr(ratelimit, "check", lambda *a, **k: None)


def container_of(s: Setup, sh: dict[str, Any]) -> str:
    number: str = ok(s.ops.get(f"/shipments/{sh['id']}"))["containers"][0]["number"]
    return number


def public(container: str, reference: str) -> tuple[int, Any]:
    return ApiClient(None).post("/public/track", {"container_number": container, "reference": reference})


def test_office_finds_shipments_by_container_number(s: Setup, world: World) -> None:
    sh, _ = dispatched(s)
    number = container_of(s, sh)
    found = ok(s.ops.get(f"/shipments/by-container/{number.lower()}"))  # case-insensitive
    assert [x["id"] for x in found] == [sh["id"]]
    assert ok(s.ops.get(f"/shipments/by-container/{container_number(9999)}")) == []
    assert ok(client_for(world.m("bravo_admin")).get(f"/shipments/by-container/{number}")) == []  # isolation


def test_customer_finds_only_their_own_container(s: Setup, world: World) -> None:
    sh, _ = dispatched(s)
    number = container_of(s, sh)
    member = world.m("alpha_customer")
    portal = client_for(member)
    assert ok(portal.get(f"/shipments/by-container/{number}")) == []  # not linked to a customer yet
    with tenant_context(world.tenants["alpha"]):
        identity.attach_customer_profile(member.membership_id, uuid.UUID(s.customer_id))
    assert [x["id"] for x in ok(portal.get(f"/shipments/by-container/{number}"))] == [sh["id"]]

    other = ok(post(s.ops, "/customers", {"name": "TEST Customer Two"}), 201)
    c2 = ok(post(s.ops, "/containers", {"number": container_number(2002), "size_ft": 20}), 201)
    ok(
        post(
            s.ops,
            "/shipments",
            {
                "customer_id": other["id"],
                "origin_label": "A",
                "destination_label": "B",
                "container_ids": [c2["id"]],
            },
        ),
        201,
    )
    assert ok(portal.get(f"/shipments/by-container/{c2['number']}")) == []  # another customer's container


def test_public_lookup_needs_container_and_reference(s: Setup) -> None:
    sh, _ = dispatched(s)
    number = container_of(s, sh)
    view = ok(public(f" {number.lower()} ", sh["reference"].lower()))
    assert view["reference"] == sh["reference"] and view["status"] == "dispatched"
    flat = str(view)
    for secret in (s.driver_id, s.vehicle_id, "driver", "plate"):
        assert secret not in flat
    err(public(number, "SHP-000000-WRONG1"), 404, "not_found")  # right container, wrong reference
    err(public(container_number(9999), sh["reference"]), 404, "not_found")  # wrong container
    code, _ = public(number, "")
    assert code == 422


def test_public_lookup_ignores_drafts(s: Setup) -> None:
    draft = new_shipment(s)  # draft: not on the road, never public
    err(public(container_of(s, draft), draft["reference"]), 404, "not_found")


def test_public_lookup_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def strict(bucket: str, key: str, *, limit: int, window_seconds: int = 60) -> None:
        calls.append(bucket)
        from corridor.core.api import ApiError

        raise ApiError(429, "rate_limited", "Too many requests.")

    monkeypatch.setattr(ratelimit, "check", strict)
    err(public("TSTU0010012", "SHP-261123-AAAAAA"), 429, "rate_limited")
    assert calls == ["public_track"]
