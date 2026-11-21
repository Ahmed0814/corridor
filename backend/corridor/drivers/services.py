"""drivers public interface (D-005). Personal data is protected (MASTER_PROMPT §3, D-019)."""

from __future__ import annotations

import uuid
from typing import Any

from django.utils import timezone

from corridor.core import crypto
from corridor.core.api import ApiError
from corridor.core.lifecycle import lock, not_found, rule
from corridor.core.pagination import paginate
from corridor.drivers.models import Driver
from corridor.drivers.schemas import ConsentIn, DriverIn, DriverOut, DriverPage, DriverUpdateIn
from corridor.identity.schemas import RequestContext, Scope


def _visible(ctx: RequestContext) -> Any:
    qs = Driver.objects.all()
    if ctx.scope == Scope.DRIVER:
        return qs.filter(id=ctx.driver_id) if ctx.driver_id else qs.none()
    if ctx.scope != Scope.TENANT:
        return qs.none()
    return qs


def _out(ctx: RequestContext, d: Driver) -> DriverOut:
    own = ctx.driver_id is not None and ctx.driver_id == d.id
    pii = own or ctx.has("drivers.pii")
    return DriverOut(
        id=d.id,
        full_name=d.full_name,
        phone_e164=(d.phone_e164 or None) if pii else None,
        license_number=(crypto.decrypt(d.license_number_enc) if d.license_number_enc else None)
        if pii
        else None,
        license_expiry=d.license_expiry,
        employment_status=d.employment_status,
        tracking_consent=d.tracking_consent,
        tracking_consent_at=d.tracking_consent_at,
        membership_id=d.membership_id,
        created_at=d.created_at,
    )


def _set_license(d: Driver, number: str) -> None:
    number = "".join(number.split()).upper()
    if not number:
        d.license_number_enc, d.license_number_hash = "", ""
        return
    digest = crypto.lookup_hash(number)
    if Driver.objects.filter(license_number_hash=digest).exclude(id=d.id).exists():
        raise ApiError(409, "conflict", "Another driver already has this license number.")
    d.license_number_enc, d.license_number_hash = crypto.encrypt(number), digest


def list_drivers(ctx: RequestContext, *, q: str | None, cursor: str | None, limit: int | None) -> DriverPage:
    qs = _visible(ctx)
    if q:
        qs = qs.filter(full_name__icontains=q)
    rows, nxt = paginate(qs, cursor, limit)
    return DriverPage(items=[_out(ctx, d) for d in rows], next_cursor=nxt)


def get_driver(ctx: RequestContext, driver_id: uuid.UUID) -> DriverOut:
    d = _visible(ctx).filter(id=driver_id).first()
    if d is None:
        raise not_found()
    return _out(ctx, d)


def my_profile(ctx: RequestContext) -> DriverOut:
    if ctx.scope != Scope.DRIVER or ctx.driver_id is None:
        raise not_found("No driver profile is linked to this account.")
    return get_driver(ctx, ctx.driver_id)


def create_driver(ctx: RequestContext, data: DriverIn) -> DriverOut:
    d = Driver.for_context(
        full_name=data.full_name, phone_e164=data.phone_e164, license_expiry=data.license_expiry
    )
    _set_license(d, data.license_number)
    d.save()
    return _out(ctx, d)


def update_driver(ctx: RequestContext, driver_id: uuid.UUID, data: DriverUpdateIn) -> DriverOut:
    d = lock(Driver.objects.all(), driver_id)
    fields = data.model_dump(exclude_unset=True)
    if "license_number" in fields:
        _set_license(d, fields.pop("license_number") or "")
    for field, value in fields.items():
        if value is not None or field == "license_expiry":
            setattr(d, field, value)
    d.save()
    return _out(ctx, d)


def set_consent(ctx: RequestContext, data: ConsentIn) -> DriverOut:
    """A driver records (or withdraws) consent to trip-time location tracking for themselves."""
    if ctx.scope != Scope.DRIVER or ctx.driver_id is None:
        raise not_found("No driver profile is linked to this account.")
    d = lock(Driver.objects.all(), ctx.driver_id)
    d.tracking_consent = data.tracking_consent
    d.tracking_consent_at = timezone.now()
    d.save(update_fields=["tracking_consent", "tracking_consent_at", "updated_at"])
    return _out(ctx, d)


def link_membership(ctx: RequestContext, driver_id: uuid.UUID, membership_id: uuid.UUID) -> DriverOut:
    """Connect a driver profile to the driver's sign-in membership (same company, role driver)."""
    from corridor.identity import services as identity

    d = lock(Driver.objects.all(), driver_id)
    rule(
        d.membership_id is None or d.membership_id == membership_id,
        "already_linked",
        "This driver profile is linked to another account.",
    )
    if Driver.objects.filter(membership_id=membership_id).exclude(id=d.id).exists():
        raise ApiError(409, "already_linked", "That account is linked to another driver profile.")
    identity.attach_driver_profile(membership_id, d.id)
    d.membership_id = membership_id
    d.save(update_fields=["membership_id", "updated_at"])
    return _out(ctx, d)


# ---------------------------------------------------------------- used by trips


def assert_driver_assignable(driver_id: uuid.UUID) -> None:
    d = Driver.objects.select_for_update().filter(id=driver_id).first()
    if d is None:
        raise not_found("Driver not found.")
    rule(
        d.employment_status == Driver.Employment.ACTIVE,
        "driver_unavailable",
        f"The driver is {d.employment_status}.",
        {"driver_id": str(d.id)},
    )
    if d.license_expiry is not None:
        rule(
            d.license_expiry >= timezone.localdate(),
            "driver_license_expired",
            "The driver's license has expired.",
            {"driver_id": str(d.id), "license_expiry": d.license_expiry.isoformat()},
        )


def names(driver_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Driver.objects.filter(id__in=driver_ids).values_list("id", "full_name"))
