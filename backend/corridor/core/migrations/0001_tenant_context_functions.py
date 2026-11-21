"""SQL helpers used by every RLS policy (docs/database/erd.md §5).

They read the transaction-local settings written by corridor.core.tenancy. An unset or empty
setting yields NULL, which matches no row (default deny).
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION app_tenant_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_user_id() RETURNS uuid
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;

CREATE OR REPLACE FUNCTION app_user_sub() RETURNS text
    LANGUAGE sql STABLE PARALLEL SAFE
    AS $$ SELECT NULLIF(current_setting('app.user_sub', true), '') $$;
"""

REVERSE = """
DROP FUNCTION IF EXISTS app_tenant_id();
DROP FUNCTION IF EXISTS app_user_id();
DROP FUNCTION IF EXISTS app_user_sub();
"""


class Migration(migrations.Migration):
    initial = True
    dependencies: list[tuple[str, str]] = []
    operations = [migrations.RunSQL(SQL, REVERSE)]
