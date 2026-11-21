"""shipments Ninja router. Every state change is an explicit endpoint (no generic status update)."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.identity.services import ctx_of, requires, tenant_auth
from corridor.shipments import services
from corridor.shipments.schemas import (
    BorderIn,
    CorrectionIn,
    DeliverIn,
    ReasonIn,
    ShipmentEventOut,
    ShipmentIn,
    ShipmentOut,
    ShipmentPage,
    ShipmentUpdateIn,
)

router = Router(tags=["shipments"], auth=tenant_auth)


@router.get("/shipments", response=ShipmentPage, summary="List shipments (scoped to the caller)")
@requires("shipments.read")
def list_shipments(
    request: HttpRequest,
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    q: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> ShipmentPage:
    return services.list_shipments(
        ctx_of(request), status=status, customer_id=customer_id, q=q, cursor=cursor, limit=limit
    )


@router.post("/shipments", response={201: ShipmentOut}, summary="Create a shipment (draft)")
@requires("shipments.write")
@idempotent
def create_shipment(request: HttpRequest, payload: ShipmentIn) -> Status[ShipmentOut]:
    return Status(201, services.create_shipment(ctx_of(request), payload))


@router.get("/shipments/{shipment_id}", response=ShipmentOut, summary="A shipment")
@requires("shipments.read")
def get_shipment(request: HttpRequest, shipment_id: uuid.UUID) -> ShipmentOut:
    return services.get_shipment(ctx_of(request), shipment_id)


@router.patch("/shipments/{shipment_id}", response=ShipmentOut, summary="Edit a draft shipment")
@requires("shipments.write")
@idempotent
def update_shipment(request: HttpRequest, shipment_id: uuid.UUID, payload: ShipmentUpdateIn) -> ShipmentOut:
    return services.update_shipment(ctx_of(request), shipment_id, payload)


@router.get("/shipments/{shipment_id}/events", response=list[ShipmentEventOut], summary="Status history")
@requires("shipments.read")
def list_events(request: HttpRequest, shipment_id: uuid.UUID) -> list[ShipmentEventOut]:
    return services.list_events(ctx_of(request), shipment_id)


@router.post(
    "/shipments/{shipment_id}/confirm", response=ShipmentOut, summary="Confirm (reserves containers)"
)
@requires("shipments.write")
@idempotent
def confirm(request: HttpRequest, shipment_id: uuid.UUID) -> ShipmentOut:
    return services.confirm_shipment(ctx_of(request), shipment_id)


@router.post(
    "/shipments/{shipment_id}/cancel", response=ShipmentOut, summary="Cancel a draft or confirmed shipment"
)
@requires("shipments.write")
@idempotent
def cancel(request: HttpRequest, shipment_id: uuid.UUID, payload: ReasonIn) -> ShipmentOut:
    return services.cancel_shipment(ctx_of(request), shipment_id, payload.reason)


@router.post(
    "/shipments/{shipment_id}/dispatch", response=ShipmentOut, summary="Dispatch (needs an assigned trip)"
)
@requires("shipments.dispatch")
@idempotent
def dispatch(request: HttpRequest, shipment_id: uuid.UUID) -> ShipmentOut:
    return services.dispatch_shipment(ctx_of(request), shipment_id)


@router.post(
    "/shipments/{shipment_id}/border-arrival", response=ShipmentOut, summary="Record arrival at a border"
)
@requires("shipments.write")
@idempotent
def border_arrival(request: HttpRequest, shipment_id: uuid.UUID, payload: BorderIn) -> ShipmentOut:
    return services.record_border_arrival(ctx_of(request), shipment_id, payload)


@router.post(
    "/shipments/{shipment_id}/border-clearance",
    response=ShipmentOut,
    summary="Confirm border/customs clearance (authorized operators only)",
)
@requires("shipments.confirm_clearance")
@idempotent
def border_clearance(request: HttpRequest, shipment_id: uuid.UUID, payload: BorderIn) -> ShipmentOut:
    return services.confirm_border_clearance(ctx_of(request), shipment_id, payload)


@router.post("/shipments/{shipment_id}/deliver", response=ShipmentOut, summary="Confirm delivery")
@requires("delivery.confirm")
@idempotent
def deliver(request: HttpRequest, shipment_id: uuid.UUID, payload: DeliverIn) -> ShipmentOut:
    return services.deliver_shipment(ctx_of(request), shipment_id, payload)


@router.post(
    "/shipments/{shipment_id}/delivery-failed", response=ShipmentOut, summary="Record a failed delivery"
)
@requires("delivery.confirm")
@idempotent
def delivery_failed(request: HttpRequest, shipment_id: uuid.UUID, payload: ReasonIn) -> ShipmentOut:
    return services.record_failed_delivery(ctx_of(request), shipment_id, payload.reason)


@router.post(
    "/shipments/{shipment_id}/reattempt", response=ShipmentOut, summary="Reattempt a failed delivery"
)
@requires("shipments.dispatch")
@idempotent
def reattempt(request: HttpRequest, shipment_id: uuid.UUID) -> ShipmentOut:
    return services.reattempt_delivery(ctx_of(request), shipment_id)


@router.post("/shipments/{shipment_id}/delay", response=ShipmentOut, summary="Mark delayed")
@requires("shipments.write")
@idempotent
def delay(request: HttpRequest, shipment_id: uuid.UUID, payload: ReasonIn) -> ShipmentOut:
    return services.mark_delayed(ctx_of(request), shipment_id, payload.reason)


@router.post("/shipments/{shipment_id}/clear-delay", response=ShipmentOut, summary="Clear the delayed flag")
@requires("shipments.write")
@idempotent
def clear_delay(request: HttpRequest, shipment_id: uuid.UUID) -> ShipmentOut:
    return services.clear_delay(ctx_of(request), shipment_id)


@router.post(
    "/shipments/{shipment_id}/corrections",
    response=ShipmentOut,
    summary="Correct the status (reason required, recorded as a new event)",
)
@requires("shipments.correct")
@idempotent
def correct(request: HttpRequest, shipment_id: uuid.UUID, payload: CorrectionIn) -> ShipmentOut:
    return services.correct_status(ctx_of(request), shipment_id, payload)
