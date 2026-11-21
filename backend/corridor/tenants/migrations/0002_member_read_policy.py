"""Let a user see the tenants they belong to (the tenant picker), not only the current one."""

from django.db import migrations

SQL = """
CREATE POLICY tenant_member_read ON tenants FOR SELECT TO corridor_app USING (
    EXISTS (SELECT 1 FROM tenant_memberships m
            WHERE m.tenant_id = tenants.id AND m.user_id = app_user_id())
);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("tenants", "0001_initial"),
        ("identity", "0002_roles_memberships"),
    ]
    operations = [migrations.RunSQL(SQL, "DROP POLICY IF EXISTS tenant_member_read ON tenants;")]
