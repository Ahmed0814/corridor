"""Team management links: a customer-role member gets portal access to one customer company, and the
member list shows which driver or customer profile each membership is linked to.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support import World, client_for
from tests.test_logistics import Setup, err, ok, post, s  # noqa: F401  (s is a fixture)

pytestmark = pytest.mark.django_db


def member(c: Any, membership_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = ok(c.get("/memberships"))
    return next(m for m in rows if m["id"] == membership_id)


def test_portal_user_link_gives_access_to_that_customer_only(s: Setup, world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    portal_member = str(world.m("alpha_customer").membership_id)
    other = ok(post(s.ops, "/customers", {"name": "TEST Customer Two"}), 201)

    # Only users.manage holders may link (ops manager and dispatcher may not).
    err(
        post(s.ops, f"/customers/{s.customer_id}/portal-users", {"membership_id": portal_member}),
        403,
        "forbidden",
    )
    err(
        post(s.disp, f"/customers/{s.customer_id}/portal-users", {"membership_id": portal_member}),
        403,
        "forbidden",
    )

    # A non-customer membership cannot be linked.
    dispatcher_member = str(world.m("alpha_dispatcher").membership_id)
    err(
        post(admin, f"/customers/{s.customer_id}/portal-users", {"membership_id": dispatcher_member}),
        409,
        "wrong_role",
    )

    ok(post(admin, f"/customers/{s.customer_id}/portal-users", {"membership_id": portal_member}))
    assert member(admin, portal_member)["customer_id"] == s.customer_id
    # Linking again to the same customer is fine; to another customer is refused.
    ok(post(admin, f"/customers/{s.customer_id}/portal-users", {"membership_id": portal_member}))
    err(
        post(admin, f"/customers/{other['id']}/portal-users", {"membership_id": portal_member}),
        409,
        "already_linked",
    )

    portal = client_for(world.m("alpha_customer"))
    ok(portal.get("/shipments"))  # customer scope now resolves to that customer


def test_portal_user_link_is_tenant_isolated(s: Setup, world: World) -> None:
    bravo_admin = client_for(world.m("bravo_admin"))
    portal_member = str(world.m("alpha_customer").membership_id)
    # Bravo cannot see alpha's customer, nor link alpha's member.
    err(
        post(bravo_admin, f"/customers/{s.customer_id}/portal-users", {"membership_id": portal_member}),
        404,
        "not_found",
    )


def test_member_list_shows_driver_link(s: Setup, world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    driver_member = str(world.m("alpha_driver").membership_id)
    # The Setup fixture already linked the alpha driver profile to this membership.
    assert member(admin, driver_member)["driver_id"] == s.driver_id
    assert member(admin, str(world.m("alpha_dispatcher").membership_id))["driver_id"] is None
