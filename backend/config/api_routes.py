"""Mount every module's Ninja router on the single /api/v1 API.

Lives in config/ (outside the corridor package) because core must not import modules' api.py
files (module boundaries, D-005).
"""

from __future__ import annotations

from corridor.audit.api import router as audit_router
from corridor.core.api import api, meta
from corridor.identity.api import me_router, platform_router
from corridor.identity.api import router as identity_router
from corridor.identity.services import PUBLIC_ATTR
from corridor.tenants.api import router as tenants_router

__all__ = ["api"]

setattr(meta, PUBLIC_ATTR, True)  # /api/v1/meta is public by design (no tenant data)

api.add_router("", me_router)
api.add_router("", identity_router)
api.add_router("", tenants_router)
api.add_router("", audit_router)
api.add_router("", platform_router)
