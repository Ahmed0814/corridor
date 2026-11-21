"""tenants public interface. Other modules may import only this file and schemas.py (D-005)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from corridor.core.platform import PLATFORM_DB, current_platform_actor
from corridor.core.tenancy import require_tenant_id
from corridor.tenants.models import Tenant
from corridor.tenants.schemas import TenantInfo, TenantProfile

ACTIVE = Tenant.Status.ACTIVE
SUSPENDED = Tenant.Status.SUSPENDED

# Tenant settings the company may change, with their validators. Unknown keys are rejected so a
# client cannot smuggle flags (e.g. "allow_exact_public_position") that later code would trust.
_SETTINGS_SCHEMA: dict[str, type] = {
    "timezone": str,
    "default_language": str,
    "freshness_live_seconds": int,
    "freshness_delayed_seconds": int,
    "freshness_stale_seconds": int,
}


class TenantNotFound(Exception):
    pass


class InvalidTenantSettings(ValueError):
    pass


def _info(t: Tenant) -> TenantInfo:
    return TenantInfo(id=t.id, slug=t.slug, name=t.name, status=t.status, is_demo=t.is_demo)


def tenants_by_ids(ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, TenantInfo]:
    """Tenants visible to the current user (RLS: current tenant + own memberships)."""
    return {t.id: _info(t) for t in Tenant.objects.filter(id__in=list(ids))}


def current_profile() -> TenantProfile:
    t = Tenant.objects.filter(id=require_tenant_id()).first()
    if t is None:
        raise TenantNotFound
    return TenantProfile(**_info(t).model_dump(), settings=t.settings, created_at=t.created_at)


def validate_settings(values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        expected = _SETTINGS_SCHEMA.get(key)
        if expected is None:
            raise InvalidTenantSettings(f"unknown setting {key!r}")
        if not isinstance(value, expected) or isinstance(value, bool):
            raise InvalidTenantSettings(f"setting {key!r} must be {expected.__name__}")
    return values


def update_current(*, name: str | None, settings: dict[str, Any] | None) -> tuple[TenantProfile, list[str]]:
    """Company-side update. Returns the new profile and the list of changed fields."""
    t = Tenant.objects.select_for_update().filter(id=require_tenant_id()).first()
    if t is None:
        raise TenantNotFound
    changed: list[str] = []
    if name is not None and name != t.name:
        t.name = name
        changed.append("name")
    if settings is not None:
        merged = {**t.settings, **validate_settings(settings)}
        if merged != t.settings:
            t.settings = merged
            changed.append("settings")
    if changed:
        t.save(update_fields=[*changed, "updated_at"])  # column grants: name, settings, updated_at
    return current_profile(), changed


# --------------------------------------------------------------------------- platform path


def _require_platform() -> None:
    if current_platform_actor() is None:
        raise PermissionError("platform operations require platform_session()")


def platform_list() -> list[TenantInfo]:
    _require_platform()
    return [_info(t) for t in Tenant.objects.using(PLATFORM_DB).order_by("slug")]


def platform_create(*, slug: str, name: str, is_demo: bool) -> TenantInfo:
    _require_platform()
    t = Tenant(slug=slug, name=name, is_demo=is_demo, status=ACTIVE)
    t.save(using=PLATFORM_DB)
    return _info(t)


def platform_set_status(tenant_id: uuid.UUID, status: str) -> tuple[TenantInfo, str]:
    """Returns the tenant and its previous status."""
    _require_platform()
    t = Tenant.objects.using(PLATFORM_DB).select_for_update().filter(id=tenant_id).first()
    if t is None:
        raise TenantNotFound
    previous = t.status
    if previous != status:
        t.status = status
        t.save(using=PLATFORM_DB, update_fields=["status", "updated_at"])
    return _info(t), previous


def platform_slug_exists(slug: str) -> bool:
    _require_platform()
    return Tenant.objects.using(PLATFORM_DB).filter(slug=slug).exists()
