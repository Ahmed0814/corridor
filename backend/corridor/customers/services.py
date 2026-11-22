"""customers public interface (D-005). Scope: customer users see only their own customer record."""

from __future__ import annotations

import uuid

from corridor.core.lifecycle import not_found
from corridor.core.pagination import paginate
from corridor.customers.models import Customer, CustomerContact
from corridor.customers.schemas import (
    ContactIn,
    ContactOut,
    CustomerDetail,
    CustomerIn,
    CustomerOut,
    CustomerPage,
    CustomerUpdateIn,
)
from corridor.identity.schemas import RequestContext, Scope


def _visible(ctx: RequestContext):  # type: ignore[no-untyped-def]
    qs = Customer.objects.all()
    if ctx.scope == Scope.CUSTOMER:
        return qs.filter(id=ctx.customer_id) if ctx.customer_id else qs.none()
    if ctx.scope != Scope.TENANT:
        return qs.none()
    return qs


def _out(c: Customer) -> CustomerOut:
    return CustomerOut.model_validate(c, from_attributes=True)


def _detail(c: Customer) -> CustomerDetail:
    contacts = [ContactOut.model_validate(x, from_attributes=True) for x in c.contacts.order_by("name")]
    return CustomerDetail(**_out(c).model_dump(), contacts=contacts)


def list_customers(
    ctx: RequestContext, *, q: str | None, cursor: str | None, limit: int | None
) -> CustomerPage:
    qs = _visible(ctx)
    if q:
        qs = qs.filter(name__icontains=q)
    rows, nxt = paginate(qs, cursor, limit)
    return CustomerPage(items=[_out(c) for c in rows], next_cursor=nxt)


def get_customer(ctx: RequestContext, customer_id: uuid.UUID) -> CustomerDetail:
    c = _visible(ctx).filter(id=customer_id).first()
    if c is None:
        raise not_found()
    return _detail(c)


def create_customer(ctx: RequestContext, data: CustomerIn) -> CustomerDetail:
    c = Customer.for_context(**data.model_dump())
    c.save()
    return _detail(c)


def update_customer(ctx: RequestContext, customer_id: uuid.UUID, data: CustomerUpdateIn) -> CustomerDetail:
    c = _visible(ctx).select_for_update().filter(id=customer_id).first()
    if c is None:
        raise not_found()
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(c, field, value)
    c.save()
    return _detail(c)


def add_contact(ctx: RequestContext, customer_id: uuid.UUID, data: ContactIn) -> CustomerDetail:
    c = _visible(ctx).filter(id=customer_id).first()
    if c is None:
        raise not_found()
    CustomerContact.for_context(customer=c, **data.model_dump()).save()
    return _detail(c)


# ---------------------------------------------------------------- used by other modules


def is_active_customer(customer_id: uuid.UUID) -> bool:
    return Customer.objects.filter(id=customer_id, status=Customer.Status.ACTIVE).exists()


def names(customer_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Customer.objects.filter(id__in=customer_ids).values_list("id", "name"))


def email_of(customer_id: uuid.UUID) -> str | None:
    email = Customer.objects.filter(id=customer_id).values_list("email", flat=True).first()
    return email or None


def link_portal_user(ctx: RequestContext, customer_id: uuid.UUID, membership_id: uuid.UUID) -> CustomerDetail:
    """Give a customer-role member access to this customer's shipments in the portal (D-016).
    Only tenant staff can do this; the membership must be a customer membership of this company."""
    from corridor.identity import services as identity

    if ctx.scope != Scope.TENANT:
        raise not_found()
    c = _visible(ctx).select_for_update().filter(id=customer_id).first()
    if c is None:
        raise not_found()
    identity.attach_customer_profile(membership_id, c.id)
    return _detail(c)
