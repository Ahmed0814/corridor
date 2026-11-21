"""Migration helpers for RLS policies and grants (DECISIONS D-007, D-018; erd.md §5).

Every tenant-owned table gets, in the migration that creates it:

    operations = [migrations.CreateModel(...), *tenant_rls("shipments")]

Roles are fixed names created by backend/db/bootstrap_roles.sql. Grants are explicit per table,
so a table that nobody granted is unreachable for the runtime roles (fail closed).
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import migrations

APP_ROLE = "corridor_app"
RELAY_ROLE = "corridor_relay"
PLATFORM_ROLE = "corridor_platform"

READ_WRITE = ("SELECT", "INSERT", "UPDATE", "DELETE")
APPEND_ONLY = ("SELECT", "INSERT")

TENANT_PREDICATE = "tenant_id = app_tenant_id()"


def _q(identifier: str) -> str:
    if not identifier.replace("_", "").isalnum():
        raise ValueError(f"unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def grant(table: str, privileges: Iterable[str], role: str = APP_ROLE) -> migrations.RunSQL:
    privs = ", ".join(privileges)
    return migrations.RunSQL(
        sql=f"GRANT {privs} ON {_q(table)} TO {role};",
        reverse_sql=f"REVOKE {privs} ON {_q(table)} FROM {role};",
    )


def tenant_rls(
    table: str,
    *,
    privileges: Iterable[str] = READ_WRITE,
    platform_privileges: Iterable[str] = (),
) -> list[migrations.RunSQL]:
    """ENABLE + FORCE RLS, the standard tenant_isolation policy and the app-role grants.

    If app.tenant_id is unset, app_tenant_id() is NULL and `tenant_id = NULL` matches nothing:
    default deny. FORCE makes the policy apply to the table owner too.
    """
    t = _q(table)
    ops = [
        migrations.RunSQL(
            sql=f"""
                ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
                ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
                CREATE POLICY tenant_isolation ON {t} TO {APP_ROLE}
                    USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE});
            """,
            reverse_sql=f"""
                DROP POLICY IF EXISTS tenant_isolation ON {t};
                ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY;
                ALTER TABLE {t} DISABLE ROW LEVEL SECURITY;
            """,
        ),
        grant(table, privileges),
    ]
    platform_privileges = tuple(platform_privileges)
    if platform_privileges:
        ops += platform_access(table, platform_privileges)
    return ops


def platform_access(table: str, privileges: Iterable[str]) -> list[migrations.RunSQL]:
    """The audited Super Admin path (core.platform) may see every row of this table."""
    t = _q(table)
    return [
        migrations.RunSQL(
            sql=f"CREATE POLICY platform_all ON {t} TO {PLATFORM_ROLE} USING (true) WITH CHECK (true);",
            reverse_sql=f"DROP POLICY IF EXISTS platform_all ON {t};",
        ),
        grant(table, privileges, PLATFORM_ROLE),
    ]
