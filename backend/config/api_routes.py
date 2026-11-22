"""Mount every module's Ninja router on the single /api/v1 API.

Lives in config/ (outside the corridor package) because core must not import modules' api.py
files (module boundaries, D-005).
"""

from __future__ import annotations

from corridor.audit.api import router as audit_router
from corridor.containers.api import router as containers_router
from corridor.core.api import api, meta
from corridor.customers.api import router as customers_router
from corridor.dispatch.api import router as dispatch_router
from corridor.documents.api import router as documents_router
from corridor.drivers.api import router as drivers_router
from corridor.fleet.api import router as fleet_router
from corridor.geofencing.api import router as geofencing_router
from corridor.identity.api import me_router, platform_router
from corridor.identity.api import router as identity_router
from corridor.identity.services import PUBLIC_ATTR
from corridor.notifications.api import router as notifications_router
from corridor.shipments.api import public_router as public_shipments_router
from corridor.shipments.api import router as shipments_router
from corridor.tenants.api import router as tenants_router
from corridor.tracking.api import router as tracking_router
from corridor.trips.api import router as trips_router

__all__ = ["api"]

setattr(meta, PUBLIC_ATTR, True)  # /api/v1/meta is public by design (no tenant data)
# Public tracking links: token-gated, allowlisted fields, rate limited (security-model.md §6).
from corridor.shipments.api import public_tracking  # noqa: E402

setattr(public_tracking, PUBLIC_ATTR, True)

api.add_router("", me_router)
api.add_router("", identity_router)
api.add_router("", tenants_router)
api.add_router("", audit_router)
api.add_router("", platform_router)
# Phase 3: core logistics
for _router in (
    customers_router,
    containers_router,
    fleet_router,
    drivers_router,
    shipments_router,
    trips_router,
    dispatch_router,
    tracking_router,  # Phase 4
    geofencing_router,  # Phase 6
    notifications_router,  # Phase 6
    documents_router,  # Phase 6
):
    api.add_router("", _router)
api.add_router("", public_shipments_router)
