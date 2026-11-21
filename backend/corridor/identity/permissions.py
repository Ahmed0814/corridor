"""Roles and permissions: the single source of truth (DECISIONS D-008).

The tables ``roles``, ``permissions`` and ``role_permissions`` are a mirror of this file, synced
on every ``migrate`` (identity.apps) and checked by a test. Runtime checks use this file.
docs/security/security-model.md §3.2 is generated from it (scripts/gen_permission_matrix.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClientKind(StrEnum):
    """Cognito app clients (D-006). A role may only act through its own client kinds."""

    WEB_OFFICE = "web-office"
    WEB_PORTAL = "web-portal"
    DRIVER_MOBILE = "driver-mobile"


class Scope(StrEnum):
    TENANT = "tenant"  # sees the whole tenant (subject to permissions)
    CUSTOMER = "customer"  # sees only data of membership.customer_id
    DRIVER = "driver"  # sees only assignments of membership.driver_id


PERMISSIONS: dict[str, str] = {
    "tenant.read": "Read the company profile",
    "tenant.settings": "Change company profile and settings",
    "users.manage": "Invite, suspend and reactivate members",
    "roles.assign": "Change a member's role",
    "audit.read": "Read the company audit log",
    "customers.read": "Read customers",
    "customers.write": "Create and edit customers",
    "containers.read": "Read containers",
    "containers.write": "Create and edit containers",
    "shipments.read": "Read shipments",
    "shipments.write": "Create and edit shipments",
    "shipments.dispatch": "Dispatch shipments",
    "shipments.confirm_clearance": "Confirm border/customs clearance",
    "shipments.correct": "Record corrections on shipments",
    "trips.assign": "Assign vehicles and drivers to trips",
    "trips.start": "Start trips",
    "trips.pause": "Pause and resume trips",
    "trips.complete": "Complete trips",
    "trips.act_on_behalf": "Start/pause/complete a trip on behalf of its driver (reason required)",
    "trips.correct": "Record corrections on trips",
    "fleet.read": "Read vehicles, trailers and GPS devices",
    "fleet.write": "Manage vehicles, trailers and GPS devices",
    "drivers.read": "Read driver profiles",
    "drivers.write": "Manage driver profiles",
    "drivers.pii": "See driver personal data (license number, phone)",
    "tracking.ingest": "Send GPS locations for an own tracking session",
    "tracking.read": "See live and historical locations",
    "tracking_links.create": "Create public tracking links",
    "tracking_links.revoke": "Revoke public tracking links",
    "delivery.confirm": "Confirm or fail a delivery",
    "documents.read": "Read documents",
    "documents.upload": "Upload documents",
}


@dataclass(frozen=True, slots=True)
class RoleDef:
    code: str
    name: str
    requires_mfa: bool
    scope: Scope
    clients: frozenset[ClientKind]
    permissions: frozenset[str]


_OFFICE = frozenset({ClientKind.WEB_OFFICE})
_ALL = frozenset(PERMISSIONS)

_OPS_MANAGER = frozenset(
    {
        "tenant.read",
        "customers.read",
        "customers.write",
        "containers.read",
        "containers.write",
        "shipments.read",
        "shipments.write",
        "shipments.dispatch",
        "shipments.confirm_clearance",
        "trips.assign",
        "trips.start",
        "trips.pause",
        "trips.complete",
        "trips.act_on_behalf",
        "fleet.read",
        "drivers.read",
        "tracking.read",
        "tracking_links.create",
        "tracking_links.revoke",
        "delivery.confirm",
        "documents.read",
        "documents.upload",
    }
)
_DISPATCHER = _OPS_MANAGER - {"customers.write", "shipments.confirm_clearance", "delivery.confirm"}

ROLES: dict[str, RoleDef] = {
    r.code: r
    for r in (
        RoleDef("owner", "Company Owner", True, Scope.TENANT, _OFFICE, _ALL - {"tracking.ingest"}),
        RoleDef("admin", "Company Admin", True, Scope.TENANT, _OFFICE, _ALL - {"tracking.ingest"}),
        RoleDef("ops_manager", "Operations Manager", False, Scope.TENANT, _OFFICE, _OPS_MANAGER),
        RoleDef("dispatcher", "Dispatcher", False, Scope.TENANT, _OFFICE, _DISPATCHER),
        RoleDef(
            "fleet_manager",
            "Fleet Manager",
            False,
            Scope.TENANT,
            _OFFICE,
            frozenset(
                {
                    "tenant.read",
                    "containers.read",
                    "shipments.read",
                    "fleet.read",
                    "fleet.write",
                    "drivers.read",
                    "drivers.write",
                    "drivers.pii",
                    "tracking.read",
                    "documents.read",
                }
            ),
        ),
        RoleDef(
            "finance",
            "Finance Officer",
            True,
            Scope.TENANT,
            _OFFICE,
            frozenset({"tenant.read", "customers.read", "shipments.read", "documents.read"}),
        ),
        RoleDef(
            "driver",
            "Driver",
            False,
            Scope.DRIVER,
            frozenset({ClientKind.DRIVER_MOBILE}),
            frozenset(
                {
                    "tenant.read",
                    "shipments.read",
                    "fleet.read",
                    "drivers.read",
                    "trips.start",
                    "trips.pause",
                    "trips.complete",
                    "tracking.ingest",
                    "tracking.read",
                    "delivery.confirm",
                    "documents.read",
                    "documents.upload",
                }
            ),
        ),
        RoleDef(
            "customer",
            "Customer",
            False,
            Scope.CUSTOMER,
            frozenset({ClientKind.WEB_PORTAL}),
            frozenset(
                {
                    "tenant.read",
                    "customers.read",
                    "containers.read",
                    "shipments.read",
                    "tracking.read",
                    "documents.read",
                }
            ),
        ),
    )
}

# Roles a Company Admin may grant. Only an Owner may create or change another Owner.
ADMIN_ASSIGNABLE = frozenset(ROLES) - {"owner"}

# Permissions treated as privileged in audit and UI (D-006: MFA-gated roles hold them).
PRIVILEGED = frozenset({"tenant.settings", "users.manage", "roles.assign", "audit.read"})


def _validate() -> None:
    for role in ROLES.values():
        unknown = role.permissions - set(PERMISSIONS)
        if unknown:
            raise RuntimeError(f"role {role.code} references unknown permissions {sorted(unknown)}")


_validate()
