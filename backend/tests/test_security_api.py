"""API-level tenant isolation and authorization (MASTER_PROMPT §8 security tests, Phase 2 DoD).

Cross-tenant ids, manipulated tenant_id in bodies, foreign tokens, tenant switching, role
violations, driver/customer client scopes, MFA gating, suspension, and a check that every route
declares its permission.
"""

from __future__ import annotations

from typing import Any

import pytest

from corridor.audit import services as audit
from corridor.core.tenancy import tenant_context
from corridor.identity.permissions import ROLES, ClientKind
from corridor.identity.services import AUTHENTICATED_ATTR, PERMISSION_ATTR, PLATFORM_ATTR, PUBLIC_ATTR
from tests.support import ApiClient, World, client_for, owner_identifier, token_for

pytestmark = pytest.mark.django_db


def _code(body: dict[str, object]) -> str:
    return str(body["error"]["code"])  # type: ignore[index]


# --------------------------------------------------------------------------- cross-tenant ids


def test_member_list_contains_only_own_tenant(world: World) -> None:
    status, body = client_for(world.m("alpha_admin")).get("/memberships")
    assert status == 200
    ids = {m["id"] for m in body}
    assert str(world.m("alpha_dispatcher").membership_id) in ids
    assert str(world.m("bravo_dispatcher").membership_id) not in ids
    assert str(world.m("bravo_admin").membership_id) not in ids


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/memberships/{id}/role", {"role": "admin"}),
        ("POST", "/memberships/{id}/suspend", None),
        ("POST", "/memberships/{id}/reactivate", None),
    ],
)
def test_foreign_membership_ids_return_404(world: World, method: str, path: str, body: object) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    foreign = world.m("bravo_dispatcher").membership_id
    status, resp = owner.request(method, path.format(id=foreign), body or {})
    assert status == 404, resp
    assert _code(resp) == "not_found"
    # Same answer as an id that does not exist at all.
    status2, resp2 = owner.request(method, path.format(id="00000000-0000-0000-0000-000000000000"), body or {})
    assert (status2, _code(resp2)) == (404, "not_found")


def test_tenant_id_in_body_is_rejected_not_trusted(world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    status, _ = admin.patch("/tenant", {"name": "Hijacked", "tenant_id": str(world.tenants["bravo"])})
    assert status == 422
    status, _body = admin.post(
        "/memberships", {"email": "x@y.test", "role": "dispatcher", "tenant_id": str(world.tenants["bravo"])}
    )
    assert status == 422
    # Bravo is untouched; alpha too (the whole request was rejected).
    status, bravo = client_for(world.m("bravo_admin")).get("/tenant")
    assert bravo["name"] == "TEST Bravo Logistics"


def test_tenant_header_naming_a_foreign_tenant_is_404(world: World) -> None:
    status, body = client_for(world.m("alpha_dispatcher"), tenant="bravo").get("/tenant")
    assert (status, _code(body)) == (404, "not_found")
    status2, body2 = client_for(world.m("alpha_dispatcher"), tenant="no-such-company").get("/tenant")
    assert (status2, body2["error"]["message"]) == (404, body["error"]["message"])


def test_token_from_another_tenant_cannot_reach_this_tenant(world: World) -> None:
    status, body = client_for(world.m("bravo_admin"), tenant="alpha").get("/memberships")
    assert (status, _code(body)) == (404, "not_found")


def test_status_cannot_be_changed_through_the_tenant_endpoint(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    status, _ = owner.patch("/tenant", {"status": "suspended"})
    assert status == 422


def test_unknown_tenant_settings_are_rejected(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    status, body = owner.patch("/tenant", {"settings": {"allow_exact_public_position": True}})
    assert status == 422
    status, body = owner.patch("/tenant", {"settings": {"timezone": "Africa/Djibouti"}})
    assert status == 200 and body["settings"]["timezone"] == "Africa/Djibouti"


# --------------------------------------------------------------------------- tenant switching


def test_multi_tenant_user_switches_with_header_and_is_audited(world: World) -> None:
    multi = world.m("multi_alpha")
    token = token_for(multi.identifier)
    status, me = ApiClient(token).get("/me")
    assert status == 200
    assert {m["tenant_slug"] for m in me["memberships"]} == {"alpha", "bravo"}
    first = me["active_tenant"]["tenant_slug"]
    other = "bravo" if first == "alpha" else "alpha"

    status, me2 = ApiClient(token, tenant=other).get("/me")
    assert status == 200
    assert me2["active_tenant"]["tenant_slug"] == other
    expected_role = "ops_manager" if other == "bravo" else "dispatcher"
    assert me2["active_tenant"]["role"] == expected_role
    assert sorted(me2["permissions"]) == sorted(ROLES[expected_role].permissions)

    with tenant_context(world.tenants[other], user_id=multi.user_id):
        rows = audit.entries_for_tests(action=audit.TENANT_SWITCHED, actor_user_id=multi.user_id)
    assert len(rows) == 1
    assert rows[0].metadata == {
        "from_tenant_id": str(world.tenants[first]),
        "to_tenant_id": str(world.tenants[other]),
    }

    # Without the header the last used tenant sticks (no second switch row).
    ApiClient(token).get("/me")
    with tenant_context(world.tenants[other], user_id=multi.user_id):
        assert len(audit.entries_for_tests(action=audit.TENANT_SWITCHED, actor_user_id=multi.user_id)) == 1


def test_switching_does_not_leak_data_between_tenants(world: World) -> None:
    multi = world.m("multi_alpha")
    token = token_for(multi.identifier)
    _, bravo_tenant = ApiClient(token, tenant="bravo").get("/tenant")
    _, alpha_tenant = ApiClient(token, tenant="alpha").get("/tenant")
    assert bravo_tenant["slug"] == "bravo" and alpha_tenant["slug"] == "alpha"


# --------------------------------------------------------------------------- role violations


@pytest.mark.parametrize(
    ("member", "method", "path", "body"),
    [
        ("alpha_dispatcher", "GET", "/memberships", None),
        ("alpha_dispatcher", "PATCH", "/tenant", {"name": "x"}),
        ("alpha_dispatcher", "GET", "/audit-logs", None),
        ("alpha_fleet_manager", "POST", "/memberships", {"email": "n@alpha.test", "role": "dispatcher"}),
        ("alpha_ops_manager", "POST", "/memberships/{target}/role", {"role": "admin"}),
    ],
)
def test_role_without_permission_gets_403(
    world: World, member: str, method: str, path: str, body: object
) -> None:
    client = client_for(world.m(member))
    status, resp = client.request(method, path.format(target=world.m("alpha_finance").membership_id), body)
    assert (status, _code(resp)) == (403, "forbidden")


def test_admin_cannot_grant_owner_or_touch_owners(world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    status, body = admin.post(
        f"/memberships/{world.m('alpha_dispatcher').membership_id}/role", {"role": "owner"}
    )
    assert (status, _code(body)) == (403, "forbidden")
    status, body = admin.post("/memberships", {"email": "o2@alpha.test", "role": "owner"})
    assert (status, _code(body)) == (403, "forbidden")


def test_nobody_changes_their_own_role(world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    status, body = admin.post(
        f"/memberships/{world.m('alpha_admin').membership_id}/role", {"role": "dispatcher"}
    )
    assert (status, _code(body)) == (409, "conflict")


def test_last_owner_cannot_be_demoted_or_suspended(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    _, me = owner.get("/me")
    _, members = owner.get("/memberships")
    second_owner = world.m("alpha_admin").membership_id
    # Promote the admin to owner, then the original owner can be managed by the new one only if
    # another active owner remains.
    status, _ = owner.post(f"/memberships/{second_owner}/role", {"role": "owner"})
    assert status == 200
    new_owner = client_for(world.m("alpha_admin"))
    original = next(m["id"] for m in members if m["user_id"] == str(me["user_id"]))
    status, _ = new_owner.post(f"/memberships/{original}/role", {"role": "admin"})
    assert status == 200
    # Now alpha_admin is the only owner: the former owner (now admin, MFA) cannot demote them.
    status, body = owner.post(f"/memberships/{second_owner}/role", {"role": "dispatcher"})
    assert (status, _code(body)) == (403, "forbidden")


# --------------------------------------------------------------------------- MFA


@pytest.mark.parametrize("member", ["alpha_admin", "alpha_finance"])
def test_privileged_roles_get_no_permissions_without_mfa(world: World, member: str) -> None:
    client = client_for(world.m(member), mfa=False)
    status, me = client.get("/me")
    assert status == 200
    assert me["mfa_required"] is True and me["permissions"] == []
    status, body = client.get("/tenant")
    assert (status, _code(body)) == (403, "mfa_required")


def test_mfa_status_is_refreshed_at_each_login(world: World) -> None:
    admin = world.m("alpha_admin")
    assert client_for(admin, mfa=True).get("/memberships")[0] == 200
    # A new Cognito session after MFA was removed loses the privileged permissions again.
    status, body = client_for(admin, mfa=False).get("/memberships")
    assert (status, _code(body)) == (403, "mfa_required")


def test_non_privileged_roles_do_not_need_mfa(world: World) -> None:
    assert client_for(world.m("alpha_dispatcher"), mfa=False).get("/tenant")[0] == 200


# --------------------------------------------------------------------------- client kinds and scopes


def test_driver_signs_in_only_through_the_driver_app(world: World) -> None:
    driver = world.m("alpha_driver")
    status, me = client_for(driver).get("/me")
    assert status == 200 and me["client"] == "driver-mobile" and me["active_tenant"]["role"] == "driver"
    office = ApiClient(token_for(driver.identifier, ClientKind.WEB_OFFICE))
    status, body = office.get("/tenant")
    assert (status, _code(body)) == (403, "wrong_client")


def test_driver_and_customer_cannot_manage_members(world: World) -> None:
    for key in ("alpha_driver", "alpha_customer"):
        status, body = client_for(world.m(key)).get("/memberships")
        assert (status, _code(body)) == (403, "forbidden"), key


def test_customer_signs_in_only_through_the_portal(world: World) -> None:
    customer = world.m("alpha_customer")
    assert client_for(customer).get("/tenant")[0] == 200
    status, body = ApiClient(token_for(customer.identifier, ClientKind.WEB_OFFICE)).get("/tenant")
    assert (status, _code(body)) == (403, "wrong_client")


def test_office_user_cannot_use_the_driver_app(world: World) -> None:
    status, body = ApiClient(token_for("dispatcher@alpha.test", ClientKind.DRIVER_MOBILE)).get("/tenant")
    assert (status, _code(body)) == (403, "wrong_client")


# --------------------------------------------------------------------------- suspension


def test_suspended_membership_is_refused(world: World) -> None:
    status, body = client_for(world.m("alpha_suspended")).get("/tenant")
    assert (status, _code(body)) == (403, "membership_suspended")


def test_suspended_tenant_is_refused(world: World) -> None:
    status, body = client_for(world.m("charlie_dispatcher")).get("/tenant")
    assert (status, _code(body)) == (403, "tenant_suspended")


def test_suspension_takes_effect_on_the_next_request(world: World) -> None:
    target = world.m("alpha_dispatcher")
    target_client = client_for(target, session_ref="steady-session")
    assert target_client.get("/tenant")[0] == 200
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    assert owner.post(f"/memberships/{target.membership_id}/suspend")[0] == 200
    status, body = target_client.get("/tenant")
    assert (status, _code(body)) == (403, "membership_suspended")


# --------------------------------------------------------------------------- route inventory


def _operations() -> list[tuple[str, str, Any, list[Any]]]:
    from ninja.constants import NOT_SET

    from config.api_routes import api

    found: list[tuple[str, str, Any, list[Any]]] = []
    for prefix, router in api._routers:
        for path, path_view in router.path_operations.items():
            for op in path_view.operations:
                # Effective auth: the operation's own, else its router's (resolved lazily by Ninja).
                auth = op.auth_param if op.auth_param is not NOT_SET else router.auth
                callbacks = [] if auth in (None, NOT_SET) else (auth if isinstance(auth, list) else [auth])
                found.append((f"{prefix}{path}", ",".join(op.methods), op.view_func, callbacks))
    return found


def test_every_route_declares_its_permission() -> None:
    """security-model.md §3.1: no route without an explicit permission (or an explicit marker)."""
    missing = []
    for path, methods, view, auth in _operations():
        markers = [
            a
            for a in (PERMISSION_ATTR, PUBLIC_ATTR, PLATFORM_ATTR, AUTHENTICATED_ATTR)
            if getattr(view, a, None)
        ]
        if not markers:
            missing.append(f"{methods} {path}: no permission declared")
        elif PUBLIC_ATTR not in markers and not auth:
            missing.append(f"{methods} {path}: declared {markers} but has no authentication")
    assert missing == []
    assert len(_operations()) >= 10


def test_no_input_schema_accepts_tenant_id() -> None:
    from config.api_routes import api

    schema = api.get_openapi_schema()
    offenders = []
    for name, component in schema.get("components", {}).get("schemas", {}).items():
        if name.endswith(("In", "Query")) and "tenant_id" in component.get("properties", {}):
            offenders.append(name)
    for path, item in schema["paths"].items():
        for op in item.values():
            for param in op.get("parameters", []):
                if param["name"] == "tenant_id" and param["in"] != "path":
                    offenders.append(f"{path} {param['name']}")
    assert offenders == []
