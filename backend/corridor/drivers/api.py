"""drivers Ninja router."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.drivers import services
from corridor.drivers.schemas import (
    ConsentIn,
    DriverIn,
    DriverOut,
    DriverPage,
    DriverUpdateIn,
    LinkMembershipIn,
)
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["drivers"], auth=tenant_auth)


@router.get("/drivers", response=DriverPage, summary="List drivers")
@requires("drivers.read")
def list_drivers(
    request: HttpRequest, q: str | None = None, cursor: str | None = None, limit: int | None = None
) -> DriverPage:
    return services.list_drivers(ctx_of(request), q=q, cursor=cursor, limit=limit)


@router.get("/drivers/me", response=DriverOut, summary="The signed-in driver's own profile")
@requires("drivers.read")
def my_profile(request: HttpRequest) -> DriverOut:
    return services.my_profile(ctx_of(request))


@router.post("/drivers/me/consent", response=DriverOut, summary="Record tracking consent (driver)")
@requires("drivers.read")
@idempotent
def set_consent(request: HttpRequest, payload: ConsentIn) -> DriverOut:
    return services.set_consent(ctx_of(request), payload)


@router.post("/drivers", response={201: DriverOut}, summary="Create a driver profile")
@requires("drivers.write")
@idempotent
def create_driver(request: HttpRequest, payload: DriverIn) -> Status[DriverOut]:
    return Status(201, services.create_driver(ctx_of(request), payload))


@router.get("/drivers/{driver_id}", response=DriverOut, summary="A driver")
@requires("drivers.read")
def get_driver(request: HttpRequest, driver_id: uuid.UUID) -> DriverOut:
    return services.get_driver(ctx_of(request), driver_id)


@router.patch("/drivers/{driver_id}", response=DriverOut, summary="Update a driver")
@requires("drivers.write")
@idempotent
def update_driver(request: HttpRequest, driver_id: uuid.UUID, payload: DriverUpdateIn) -> DriverOut:
    return services.update_driver(ctx_of(request), driver_id, payload)


@router.post(
    "/drivers/{driver_id}/link", response=DriverOut, summary="Link a driver to their sign-in account"
)
@requires("drivers.write")
@idempotent
def link_membership(request: HttpRequest, driver_id: uuid.UUID, payload: LinkMembershipIn) -> DriverOut:
    return services.link_membership(ctx_of(request), driver_id, payload.membership_id)
