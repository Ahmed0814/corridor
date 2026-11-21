"""Database-level isolation, run as the real application role (MASTER_PROMPT §4.4, Phase 2 DoD).

Every query here goes through the corridor_app connection the API uses.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from corridor.core.tenancy import TenantContextError, tenant_context
from corridor.identity.models import TenantMembership
from tests.support import World

pytestmark = pytest.mark.django_db

BACKEND = Path(__file__).resolve().parent.parent

# Tables with a tenant_id column whose policies differ from the standard tenant_isolation
# template, each for a documented reason.
SPECIAL_TENANT_TABLES = {
    "audit_logs": "nullable tenant_id for platform-level rows; append-only (audit 0001)",
}


def _one(sql: str, params: list[Any] | None = None) -> Any:
    with connection.cursor() as c:
        c.execute(sql, params or [])
        row = c.fetchone()
    assert row is not None
    return row[0]


def _rows(sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
    with connection.cursor() as c:
        c.execute(sql, params or [])
        return list(c.fetchall())


def _expect_db_error(sql: str, params: list[Any] | None = None, match: str = "") -> str:
    with pytest.raises(DatabaseError) as exc_info, transaction.atomic(), connection.cursor() as c:
        c.execute(sql, params or [])
    message = str(exc_info.value)
    assert re.search(match, message, re.IGNORECASE), message
    return message


# --------------------------------------------------------------------------- the role itself


def test_tests_run_as_the_application_role(no_db_context: None) -> None:
    assert _one("SELECT current_user") == "corridor_app"
    assert _one("SELECT session_user") == "corridor_app"


def test_app_role_has_no_bypassrls_superuser_or_createrole() -> None:
    row = _rows(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles"
        " WHERE rolname = 'corridor_app'"
    )[0]
    assert row == (False, False, False, False)


def test_app_role_is_not_a_member_of_the_owner_role() -> None:
    assert _one("SELECT pg_has_role('corridor_app', 'corridor_owner', 'MEMBER')") is False


def test_app_role_owns_no_tables_sequences_views_or_functions() -> None:
    owned = _rows(
        "SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = 'corridor_app'"
    )
    assert owned == []
    functions = _rows(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) = 'corridor_app'"
    )
    assert functions == []


def test_application_tables_are_owned_by_corridor_owner() -> None:
    owners: dict[str, str] = dict(
        _rows(
            "SELECT tablename, tableowner FROM pg_tables WHERE schemaname = 'public' "
            "AND tablename IN ('tenants', 'users', 'tenant_memberships', 'audit_logs', 'roles')"
        )
    )
    assert set(owners.values()) == {"corridor_owner"}, owners


def test_app_role_cannot_become_the_owner() -> None:
    _expect_db_error("SET ROLE corridor_owner", match="permission denied")


def test_app_role_cannot_turn_off_row_security() -> None:
    # row_security=off makes PostgreSQL raise instead of filtering when a policy applies.
    with transaction.atomic(), connection.cursor() as c:
        c.execute("SET LOCAL row_security = off")
        with pytest.raises(DatabaseError, match="row-level security"), transaction.atomic():
            c.execute("SELECT count(*) FROM tenant_memberships")


def test_app_role_cannot_create_objects_in_public_schema() -> None:
    _expect_db_error("CREATE TABLE sneaky (id int)", match="permission denied")


# --------------------------------------------------------------------------- RLS catalogue


def _tenant_tables() -> list[str]:
    return [
        r[0]
        for r in _rows(
            "SELECT c.table_name FROM information_schema.columns c "
            "JOIN information_schema.tables t"
            " ON t.table_name = c.table_name AND t.table_schema = c.table_schema "
            "WHERE c.table_schema = 'public' AND c.column_name = 'tenant_id' AND t.table_type = 'BASE TABLE' "
            "ORDER BY 1"
        )
    ]


def test_every_tenant_table_has_forced_rls_and_a_tenant_policy() -> None:
    tables = _tenant_tables()
    assert "tenant_memberships" in tables  # sanity: the catalogue query works
    problems = []
    for table in tables:
        enabled, forced = _rows(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", [table]
        )[0]
        policies = {
            r[0]: r
            for r in _rows("SELECT policyname, roles::text FROM pg_policies WHERE tablename = %s", [table])
        }
        if not (enabled and forced):
            problems.append(f"{table}: RLS enabled={enabled} forced={forced}")
        if table in SPECIAL_TENANT_TABLES:
            if not any("corridor_app" in r[1] for r in policies.values()):
                problems.append(f"{table}: no policy for corridor_app")
        elif "tenant_isolation" not in policies:
            problems.append(f"{table}: missing tenant_isolation policy")
    assert problems == []


@pytest.mark.parametrize("table", ["tenants", "users"])
def test_global_tables_with_tenant_data_have_forced_rls(table: str) -> None:
    assert _rows(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = %s::regclass", [table]
    ) == [(True, True)]


def test_no_table_grants_update_or_delete_on_append_only_tables() -> None:
    # Event history tables are append-only (hard rule 5, D-018).
    for table in ("audit_logs", "shipment_events", "trip_events", "container_events", "outbox_events"):
        assert _one("SELECT has_table_privilege('corridor_app', %s, 'UPDATE')", [table]) is False
        assert _one("SELECT has_table_privilege('corridor_app', %s, 'DELETE')", [table]) is False


# --------------------------------------------------------------------------- RLS bypass attempts


def test_raw_sql_without_context_sees_no_rows(world: World, no_db_context: None) -> None:
    for table in ("tenant_memberships", "tenants", "users", "audit_logs"):
        assert _one(f"SELECT count(*) FROM {table}") == 0, table  # noqa: S608 - fixed table names


def test_raw_sql_with_context_sees_only_that_tenant(world: World) -> None:
    alpha, bravo = world.tenants["alpha"], world.tenants["bravo"]
    with tenant_context(alpha):
        tenant_ids = {r[0] for r in _rows("SELECT DISTINCT tenant_id FROM tenant_memberships")}
        assert tenant_ids == {alpha}
        assert _one("SELECT count(*) FROM tenant_memberships WHERE tenant_id = %s", [bravo]) == 0
        assert _one("SELECT count(*) FROM tenants WHERE id = %s", [bravo]) == 0
        bravo_user = world.m("bravo_admin").user_id
        assert _one("SELECT count(*) FROM users WHERE id = %s", [bravo_user]) == 0


def test_cannot_insert_a_row_for_another_tenant(world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        _expect_db_error(
            "INSERT INTO tenant_memberships"
            " (id, tenant_id, user_id, role_code, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, 'dispatcher', 'active', now(), now())",
            [uuid.uuid4(), world.tenants["bravo"], world.m("alpha_dispatcher").user_id],
            match="row-level security",
        )


def test_cannot_update_or_delete_another_tenants_rows(world: World) -> None:
    target = world.m("bravo_dispatcher").membership_id
    with tenant_context(world.tenants["alpha"]), connection.cursor() as c:
        c.execute("UPDATE tenant_memberships SET role_code = 'admin' WHERE id = %s", [target])
        assert c.rowcount == 0
        c.execute("DELETE FROM tenant_memberships WHERE id = %s", [target])
        assert c.rowcount == 0


def test_cannot_move_a_row_into_another_tenant(world: World) -> None:
    mine = world.m("alpha_dispatcher").membership_id
    with tenant_context(world.tenants["alpha"]):
        _expect_db_error(
            "UPDATE tenant_memberships SET tenant_id = %s WHERE id = %s",
            [world.tenants["bravo"], mine],
            match="row-level security",
        )


def test_forged_session_variable_value_is_rejected(world: World) -> None:
    # A malformed tenant id cannot widen access: the cast fails and the query errors.
    with transaction.atomic(), connection.cursor() as c:
        c.execute("SELECT set_config('app.tenant_id', 'x'' OR true --', true)")
        with pytest.raises(DatabaseError, match="invalid input syntax for type uuid"), transaction.atomic():
            c.execute("SELECT count(*) FROM tenant_memberships")


def test_app_role_cannot_change_tenant_status_or_slug(world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        _expect_db_error("UPDATE tenants SET status = 'active'", match="permission denied")
        _expect_db_error("UPDATE tenants SET slug = 'x'", match="permission denied")


def test_app_role_cannot_escalate_a_user(world: World) -> None:
    me = world.m("alpha_dispatcher").user_id
    with tenant_context(world.tenants["alpha"], user_id=me):
        _expect_db_error(
            "UPDATE users SET is_platform_admin = true WHERE id = %s", [me], match="permission denied"
        )
        _expect_db_error("UPDATE users SET cognito_sub = 'x' WHERE id = %s", [me], match="permission denied")


def test_app_role_cannot_insert_users_directly(world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        _expect_db_error(
            "INSERT INTO users (id, password, is_superuser, email, display_name, is_platform_admin, is_staff,"
            " is_active, last_session_ref, created_at, updated_at) VALUES (gen_random_uuid(), '!', false,"
            " 'x@x.test', '', false, false, true, '', now(), now())",
            match="permission denied",
        )


def test_audit_log_is_append_only_for_the_app_role(world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        _expect_db_error("UPDATE audit_logs SET action = 'x'", match="permission denied")
        _expect_db_error("DELETE FROM audit_logs", match="permission denied")


def test_identity_upsert_requires_a_tenant_context(no_db_context: None) -> None:
    _expect_db_error(
        "SELECT identity_upsert_user('local-x', 'new@x.test', NULL, '')", match="requires a tenant context"
    )


def test_platform_policies_do_not_apply_to_the_app_role(world: World, no_db_context: None) -> None:
    # platform_all policies are TO corridor_platform; the app role gains nothing from them.
    assert _one("SELECT count(*) FROM tenants") == 0


# --------------------------------------------------------------------------- ORM layer


def test_scoped_manager_refuses_to_run_without_a_tenant(no_db_context: None) -> None:
    with pytest.raises(TenantContextError):
        list(TenantMembership.objects.all())


def test_scoped_manager_filters_by_context_tenant(world: World) -> None:
    with tenant_context(world.tenants["bravo"]):
        tenants = set(TenantMembership.objects.values_list("tenant_id", flat=True))
    assert tenants == {world.tenants["bravo"]}


def test_saving_a_row_of_another_tenant_raises(world: World) -> None:
    with tenant_context(world.tenants["alpha"]):
        m = TenantMembership(
            tenant_id=world.tenants["bravo"],
            user_id=world.m("alpha_dispatcher").user_id,
            role_id="dispatcher",
        )
        with pytest.raises(TenantContextError):
            m.save()


def test_tenant_context_restores_the_previous_tenant(world: World) -> None:
    alpha, bravo = world.tenants["alpha"], world.tenants["bravo"]
    with tenant_context(alpha):
        with tenant_context(bravo):
            assert _one("SELECT app_tenant_id()") == bravo
        assert _one("SELECT app_tenant_id()") == alpha


def test_context_cannot_be_applied_outside_a_transaction(world: World) -> None:
    from corridor.core.tenancy import apply_context

    # pytest-django wraps the test in a transaction, so simulate autocommit by checking the guard.
    assert connection.in_atomic_block
    original = connection.in_atomic_block
    try:
        connection.in_atomic_block = False
        with pytest.raises(TenantContextError):
            apply_context(tenant_id=world.tenants["alpha"])
    finally:
        connection.in_atomic_block = original


# --------------------------------------------------------------------------- code hygiene


def test_no_session_level_tenant_setting_in_code() -> None:
    """SET LOCAL only (security-model.md §4.2): never `SET app.x` or set_config(..., false)."""
    offenders = []
    session_set = re.compile(r"\bSET\s+(SESSION\s+)?app\.", re.IGNORECASE)
    session_config = re.compile(r"set_config\(\s*'app\.[a-z_]+'\s*,[^)]*,\s*false\s*\)", re.IGNORECASE)
    for path in list((BACKEND / "corridor").rglob("*.py")) + list((BACKEND / "config").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern in (session_set, session_config):
            for match in pattern.finditer(text):
                offenders.append(f"{path.relative_to(BACKEND)}: {match.group(0)}")
    assert offenders == []
