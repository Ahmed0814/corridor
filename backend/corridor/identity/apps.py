from __future__ import annotations

from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def sync_roles_and_permissions(sender: AppConfig, using: str = "default", **_: Any) -> None:
    """Mirror identity/permissions.py into roles/permissions/role_permissions (D-008).

    Runs after every `migrate`, as the migration role. Removes rows that no longer exist in code.
    """
    if sender.label != "identity":
        return
    from django.db import transaction

    from corridor.identity.models import Permission, Role, RolePermission
    from corridor.identity.permissions import PERMISSIONS, ROLES

    with transaction.atomic(using=using):
        for code, description in PERMISSIONS.items():
            Permission.objects.using(using).update_or_create(code=code, defaults={"description": description})
        for role in ROLES.values():
            Role.objects.using(using).update_or_create(
                code=role.code,
                defaults={"name": role.name, "requires_mfa": role.requires_mfa, "scope": role.scope.value},
            )
        wanted = {(r.code, p) for r in ROLES.values() for p in r.permissions}
        existing = set(RolePermission.objects.using(using).values_list("role_id", "permission_id"))
        RolePermission.objects.using(using).bulk_create(
            [RolePermission(role_id=r, permission_id=p) for r, p in sorted(wanted - existing)]
        )
        for r, p in existing - wanted:
            RolePermission.objects.using(using).filter(role_id=r, permission_id=p).delete()
        Permission.objects.using(using).exclude(code__in=PERMISSIONS).delete()
        Role.objects.using(using).exclude(code__in=ROLES).delete()


class IdentityConfig(AppConfig):
    name = "corridor.identity"
    label = "identity"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        post_migrate.connect(sync_roles_and_permissions, sender=self)
