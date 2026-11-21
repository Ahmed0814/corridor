"""The separate, audited Platform Super Admin path (MASTER_PROMPT §4.4)."""

from __future__ import annotations

from typing import Any

import pytest

from corridor.audit import services as audit
from corridor.audit.schemas import AuditEntry
from corridor.core.platform import PLATFORM_DB, PlatformAccessError, PlatformActor, platform_session
from corridor.tenants.models import Tenant
from tests.support import ApiClient, World, client_for, token_for

pytestmark = pytest.mark.django_db(databases=["default", "platform"])


def _admin(world: World, mfa: bool = True) -> ApiClient:
    return ApiClient(token_for(world.platform_admin_identifier, mfa=mfa))


def _platform_audit(**filters: Any) -> list[AuditEntry]:
    with platform_session(PlatformActor(None, "test assertion")):
        return audit.entries_for_tests(using=PLATFORM_DB, **filters)


def test_platform_alias_is_unusable_outside_a_platform_session() -> None:
    with pytest.raises(PlatformAccessError):
        Tenant.objects.using(PLATFORM_DB).count()


def test_platform_session_requires_a_reason() -> None:
    with pytest.raises(PlatformAccessError), platform_session(PlatformActor(None, "  ")):
        pass


def test_platform_admin_lists_all_tenants_and_the_read_is_audited(world: World) -> None:
    before = len(_platform_audit(action=audit.PLATFORM_READ))
    status, body = _admin(world).get("/platform/tenants")
    assert status == 200
    assert {"alpha", "bravo", "charlie"} <= {t["slug"] for t in body}
    rows = _platform_audit(action=audit.PLATFORM_READ)
    assert len(rows) == before + 1
    assert rows[-1].actor_user_id == world.platform_admin_id
    assert rows[-1].actor_kind == "platform_admin"


def test_platform_api_is_invisible_to_tenant_users(world: World) -> None:
    status, body = client_for(world.m("alpha_admin")).get("/platform/tenants")
    assert (status, body["error"]["code"]) == (404, "not_found")


def test_platform_admin_needs_mfa(world: World) -> None:
    status, body = _admin(world, mfa=False).get("/platform/tenants")
    assert (status, body["error"]["code"]) == (403, "mfa_required")


def test_create_and_suspend_a_tenant(world: World) -> None:
    admin = _admin(world)
    status, created = admin.post(
        "/platform/tenants", {"slug": "delta", "name": "TEST Delta", "owner_email": "owner@delta.test"}
    )
    assert status == 201, created
    assert _platform_audit(action=audit.TENANT_CREATED, target_id=created["id"])

    status, _ = admin.post("/platform/tenants", {"slug": "delta", "name": "x", "owner_email": "o@d.test"})
    assert status == 409

    status, body = admin.post(f"/platform/tenants/{created['id']}/suspend")
    assert status == 200 and body["status"] == "suspended"
    assert _platform_audit(action=audit.TENANT_SUSPENDED, target_id=created["id"])
    status, body = admin.post(f"/platform/tenants/{created['id']}/activate")
    assert status == 200 and body["status"] == "active"
    assert _platform_audit(action=audit.TENANT_ACTIVATED, target_id=created["id"])
    # Sign-in of a platform-created owner and refusal for a suspended tenant are covered by the
    # fixture world (created through this same path, committed): test_security_api.py.


def test_platform_inputs_reject_unknown_fields(world: World) -> None:
    status, _ = _admin(world).post(
        "/platform/tenants",
        {"slug": "echo", "name": "x", "owner_email": "o@e.test", "status": "active", "id": "x"},
    )
    assert status == 422
