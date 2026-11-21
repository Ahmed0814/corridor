"""containers Ninja router."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.containers import services
from corridor.containers.schemas import (
    AvailabilityIn,
    ContainerEventOut,
    ContainerIn,
    ContainerOut,
    ContainerPage,
    ContainerUpdateIn,
    InspectionIn,
)
from corridor.core.idempotency import idempotent
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["containers"], auth=tenant_auth)


@router.get("/containers", response=ContainerPage, summary="List containers")
@requires("containers.read")
def list_containers(
    request: HttpRequest,
    q: str | None = None,
    availability: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> ContainerPage:
    return services.list_containers(
        ctx_of(request), q=q, availability=availability, cursor=cursor, limit=limit
    )


@router.post("/containers", response={201: ContainerOut}, summary="Register a container")
@requires("containers.write")
@idempotent
def create_container(request: HttpRequest, payload: ContainerIn) -> Status[ContainerOut]:
    return Status(201, services.create_container(ctx_of(request), payload))


@router.get("/containers/{container_id}", response=ContainerOut, summary="A container")
@requires("containers.read")
def get_container(request: HttpRequest, container_id: uuid.UUID) -> ContainerOut:
    return services.get_container(ctx_of(request), container_id)


@router.patch("/containers/{container_id}", response=ContainerOut, summary="Update container details")
@requires("containers.write")
@idempotent
def update_container(
    request: HttpRequest, container_id: uuid.UUID, payload: ContainerUpdateIn
) -> ContainerOut:
    return services.update_container(ctx_of(request), container_id, payload)


@router.post("/containers/{container_id}/availability", response=ContainerOut, summary="Change availability")
@requires("containers.write")
@idempotent
def set_availability(request: HttpRequest, container_id: uuid.UUID, payload: AvailabilityIn) -> ContainerOut:
    return services.set_availability(ctx_of(request), container_id, payload)


@router.post("/containers/{container_id}/inspections", response=ContainerOut, summary="Record an inspection")
@requires("containers.write")
@idempotent
def record_inspection(request: HttpRequest, container_id: uuid.UUID, payload: InspectionIn) -> ContainerOut:
    return services.record_inspection(ctx_of(request), container_id, payload)


@router.get(
    "/containers/{container_id}/events", response=list[ContainerEventOut], summary="Container history"
)
@requires("containers.read")
def list_events(request: HttpRequest, container_id: uuid.UUID) -> list[ContainerEventOut]:
    return services.list_events(ctx_of(request), container_id)
