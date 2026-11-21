"""Grants on Django's own tables for the runtime role (fail closed: nothing else is implied).

None of these tables hold tenant data. The app role cannot create content types or
permissions; `migrate` (as corridor_migrator) does that.
"""

from django.db import migrations

from corridor.core.db import grant

READ_ONLY = (
    "django_migrations",
    "django_content_type",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "users_groups",
    "users_user_permissions",
)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_tenant_context_functions"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sessions", "0001_initial"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("identity", "0001_initial"),
    ]
    operations = [
        *[grant(t, ["SELECT"]) for t in READ_ONLY],
        grant("django_session", ["SELECT", "INSERT", "UPDATE", "DELETE"]),
        grant("django_admin_log", ["SELECT", "INSERT"]),
    ]
