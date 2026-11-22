"""customers Ninja router."""

from __future__ import annotations

import uuid

from django.http import HttpRequest
from ninja import Router, Status

from corridor.core.idempotency import idempotent
from corridor.customers import services
from corridor.customers.schemas import (
    ContactIn,
    CustomerDetail,
    CustomerIn,
    CustomerPage,
    CustomerUpdateIn,
    PortalUserLinkIn,
)
from corridor.identity.services import ctx_of, requires, tenant_auth

router = Router(tags=["customers"], auth=tenant_auth)


@router.get("/customers", response=CustomerPage, summary="List customers")
@requires("customers.read")
def list_customers(
    request: HttpRequest, q: str | None = None, cursor: str | None = None, limit: int | None = None
) -> CustomerPage:
    return services.list_customers(ctx_of(request), q=q, cursor=cursor, limit=limit)


@router.post("/customers", response={201: CustomerDetail}, summary="Create a customer")
@requires("customers.write")
@idempotent
def create_customer(request: HttpRequest, payload: CustomerIn) -> Status[CustomerDetail]:
    return Status(201, services.create_customer(ctx_of(request), payload))


@router.get("/customers/{customer_id}", response=CustomerDetail, summary="A customer with contacts")
@requires("customers.read")
def get_customer(request: HttpRequest, customer_id: uuid.UUID) -> CustomerDetail:
    return services.get_customer(ctx_of(request), customer_id)


@router.patch("/customers/{customer_id}", response=CustomerDetail, summary="Update a customer")
@requires("customers.write")
@idempotent
def update_customer(
    request: HttpRequest, customer_id: uuid.UUID, payload: CustomerUpdateIn
) -> CustomerDetail:
    return services.update_customer(ctx_of(request), customer_id, payload)


@router.post("/customers/{customer_id}/contacts", response={201: CustomerDetail}, summary="Add a contact")
@requires("customers.write")
@idempotent
def add_contact(request: HttpRequest, customer_id: uuid.UUID, payload: ContactIn) -> Status[CustomerDetail]:
    return Status(201, services.add_contact(ctx_of(request), customer_id, payload))


@router.post(
    "/customers/{customer_id}/portal-users",
    response=CustomerDetail,
    summary="Give a customer-role member portal access to this customer",
)
@requires("users.manage")
@idempotent
def link_portal_user(
    request: HttpRequest, customer_id: uuid.UUID, payload: PortalUserLinkIn
) -> CustomerDetail:
    return services.link_portal_user(ctx_of(request), customer_id, payload.membership_id)
