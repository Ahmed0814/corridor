"""Audit rows for login, role change, tenant switch and membership changes (Phase 2 DoD), plus the
invitation flow."""

from __future__ import annotations

from typing import Any

import pytest

from corridor.audit import services as audit
from corridor.audit.schemas import AuditEntry
from corridor.core.tenancy import tenant_context
from corridor.identity.local_issuer import local_sub
from corridor.identity.permissions import ClientKind
from tests.support import ApiClient, World, client_for, owner_identifier, token_for

pytestmark = pytest.mark.django_db


def _entries(world: World, tenant: str, **filters: Any) -> list[AuditEntry]:
    with tenant_context(world.tenants[tenant]):
        return audit.entries_for_tests(**filters)


def test_login_is_audited_once_per_cognito_session(world: World) -> None:
    member = world.m("alpha_ops_manager")
    before = len(_entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id))
    session_a = client_for(member, session_ref="session-a")
    session_a.get("/me")
    session_a.get("/tenant")  # same Cognito session (refreshed tokens keep origin_jti)
    client_for(member, session_ref="session-a").get("/tenant")
    after_a = _entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id)
    assert len(after_a) == before + 1
    row = after_a[-1]
    assert row.tenant_id == world.tenants["alpha"]
    assert row.metadata == {"client": "web-office"}
    assert row.request_id  # correlates with the access log line
    client_for(member, session_ref="session-b").get("/me")
    assert len(_entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id)) == before + 2


def test_failed_request_does_not_record_a_partial_login(world: World) -> None:
    member = world.m("alpha_dispatcher")
    before = len(_entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id))
    client = client_for(member, session_ref="session-x")
    status, _ = client.get("/memberships")  # 403: the whole request transaction rolls back
    assert status == 403
    assert len(_entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id)) == before
    assert client.get("/tenant")[0] == 200  # the next successful request records it
    assert len(_entries(world, "alpha", action=audit.LOGIN, actor_user_id=member.user_id)) == before + 1


def test_role_change_is_audited_and_visible_to_auditors(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    target = world.m("alpha_fleet_manager")
    status, body = owner.post(f"/memberships/{target.membership_id}/role", {"role": "dispatcher"})
    assert status == 200 and body["role"] == "dispatcher"
    rows = _entries(world, "alpha", action=audit.ROLE_CHANGED, target_id=str(target.membership_id))
    assert len(rows) == 1
    assert rows[0].metadata == {"from": "fleet_manager", "to": "dispatcher", "user_id": str(target.user_id)}
    assert rows[0].actor_kind == "user"

    status, log = owner.get("/audit-logs", tenant="alpha")
    assert status == 200
    assert any(e["action"] == "role.changed" and e["target_id"] == str(target.membership_id) for e in log)
    # Bravo's auditors never see alpha's rows.
    status, bravo_log = client_for(world.m("bravo_admin")).get("/audit-logs")
    assert status == 200
    assert all(e["tenant_id"] == str(world.tenants["bravo"]) for e in bravo_log)
    # The role change takes effect immediately for the target.
    status, me = client_for(target).get("/me")
    assert me["active_tenant"]["role"] == "dispatcher"


def test_unchanged_role_writes_no_audit_row(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    target = world.m("alpha_ops_manager")
    owner.post(f"/memberships/{target.membership_id}/role", {"role": "ops_manager"})
    assert _entries(world, "alpha", action=audit.ROLE_CHANGED, target_id=str(target.membership_id)) == []


def test_tenant_switch_is_audited_in_the_destination_tenant(world: World) -> None:
    multi = world.m("multi_alpha")
    token = token_for(multi.identifier)
    ApiClient(token, tenant="alpha").get("/me")
    ApiClient(token, tenant="bravo").get("/me")
    ApiClient(token, tenant="alpha").get("/me")
    to_bravo = _entries(world, "bravo", action=audit.TENANT_SWITCHED, actor_user_id=multi.user_id)
    to_alpha = _entries(world, "alpha", action=audit.TENANT_SWITCHED, actor_user_id=multi.user_id)
    assert [e.metadata["to_tenant_id"] for e in to_bravo] == [str(world.tenants["bravo"])]
    assert str(world.tenants["alpha"]) in [e.metadata["to_tenant_id"] for e in to_alpha]


def test_suspend_and_reactivate_are_audited(world: World) -> None:
    owner = ApiClient(token_for(owner_identifier("alpha"), mfa=True))
    target = world.m("alpha_dispatcher").membership_id
    assert owner.post(f"/memberships/{target}/suspend")[1]["status"] == "suspended"
    assert owner.post(f"/memberships/{target}/reactivate")[1]["status"] == "active"
    actions = [e.action for e in _entries(world, "alpha", target_id=str(target))]
    assert actions[-2:] == [audit.MEMBERSHIP_SUSPENDED, audit.MEMBERSHIP_REACTIVATED]


def test_invitation_flow(world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    status, member = admin.post(
        "/memberships", {"email": "New.Hire@Alpha.test", "display_name": "New Hire", "role": "dispatcher"}
    )
    assert status == 201, member
    assert member["status"] == "invited" and member["email"] == "new.hire@alpha.test"
    assert len(_entries(world, "alpha", action=audit.MEMBERSHIP_INVITED, target_id=member["id"])) == 1

    # Inviting the same person again is a conflict.
    status, body = admin.post("/memberships", {"email": "new.hire@alpha.test", "role": "dispatcher"})
    assert (status, body["error"]["code"]) == (409, "conflict")

    # First sign-in activates the membership.
    status, me = ApiClient(token_for("new.hire@alpha.test")).get("/me")
    assert status == 200 and me["active_tenant"]["status"] == "active"
    status, members = admin.get("/memberships")
    assert next(m for m in members if m["id"] == member["id"])["status"] == "active"
    assert len(_entries(world, "alpha", action=audit.MEMBERSHIP_ACTIVATED, target_id=member["id"])) == 1


def test_inviting_someone_from_another_company_reveals_nothing(world: World) -> None:
    # bravo's dispatcher exists globally; alpha can invite them (one person, many companies)
    # but learns nothing about their other memberships.
    admin = client_for(world.m("alpha_admin"))
    status, member = admin.post("/memberships", {"email": "dispatcher@bravo.test", "role": "dispatcher"})
    assert status == 201
    assert member["user_id"] == str(world.m("bravo_dispatcher").user_id)
    status, me = ApiClient(token_for("dispatcher@bravo.test"), tenant="alpha").get("/me")
    assert status == 200
    # The person sees both of their own memberships; alpha's admin only sees alpha's members.
    assert {m["tenant_slug"] for m in me["memberships"]} == {"alpha", "bravo"}


def test_driver_invitation_requires_a_phone_number(world: World) -> None:
    admin = client_for(world.m("alpha_admin"))
    status, _ = admin.post("/memberships", {"email": "d@alpha.test", "role": "driver"})
    assert status == 422
    status, member = admin.post("/memberships", {"phone_e164": "+25377123499", "role": "driver"})
    assert status == 201 and member["phone_masked"] == "+253•••99"
    assert member["email"] is None
    status, me = ApiClient(token_for("+25377123499", ClientKind.DRIVER_MOBILE)).get("/me")
    assert status == 200 and me["active_tenant"]["role"] == "driver"


def test_local_subs_are_stable_and_case_insensitive() -> None:
    assert local_sub("A@B.test") == local_sub(" a@b.test ")
