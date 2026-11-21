"""containers public interface (D-005)."""

from __future__ import annotations

import uuid

from corridor.containers.models import Container, ContainerEvent
from corridor.containers.schemas import (
    AvailabilityIn,
    ContainerEventOut,
    ContainerIn,
    ContainerOut,
    ContainerPage,
    ContainerUpdateIn,
    InspectionIn,
)
from corridor.core.api import ApiError
from corridor.core.lifecycle import assert_state, lock, not_found, rule
from corridor.core.pagination import paginate
from corridor.identity.schemas import RequestContext, Scope

# ISO 6346 letter values: A=10 ... Z=38, skipping multiples of 11.
_LETTER_VALUES: dict[str, int] = {}
_v = 10
for _ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_ch] = _v
    _v += 1


def normalise_number(raw: str) -> str:
    return "".join(raw.split()).replace("-", "").upper()


def iso6346_valid(number: str) -> bool:
    """Owner code (3 letters) + category (U, J or Z) + 6-digit serial + check digit."""
    if len(number) != 11 or not number[:4].isalpha() or not number[4:].isdigit() or number[3] not in "UJZ":
        return False
    total = 0
    for i, ch in enumerate(number[:10]):
        value = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += value * (2**i)
    return (total % 11) % 10 == int(number[10])


def _tenant_wide(ctx: RequestContext) -> None:
    if ctx.scope != Scope.TENANT:
        raise not_found()


def _out(c: Container) -> ContainerOut:
    return ContainerOut.model_validate(c, from_attributes=True)


def list_containers(
    ctx: RequestContext, *, q: str | None, availability: str | None, cursor: str | None, limit: int | None
) -> ContainerPage:
    _tenant_wide(ctx)
    qs = Container.objects.all()
    if q:
        qs = qs.filter(number__icontains=normalise_number(q))
    if availability:
        qs = qs.filter(availability=availability)
    rows, nxt = paginate(qs, cursor, limit)
    return ContainerPage(items=[_out(c) for c in rows], next_cursor=nxt)


def get_container(ctx: RequestContext, container_id: uuid.UUID) -> ContainerOut:
    _tenant_wide(ctx)
    c = Container.objects.filter(id=container_id).first()
    if c is None:
        raise not_found()
    return _out(c)


def create_container(ctx: RequestContext, data: ContainerIn) -> ContainerOut:
    _tenant_wide(ctx)
    number = normalise_number(data.number)
    if not iso6346_valid(number):
        raise ApiError(
            422,
            "validation_error",
            "Container number fails the ISO 6346 format or check digit.",
            [{"loc": ["body", "number"], "msg": "invalid ISO 6346 container number"}],
        )
    if Container.objects.filter(number=number).exists():
        raise ApiError(409, "conflict", "A container with this number already exists.")
    c = Container.for_context(**{**data.model_dump(), "number": number})
    c.save()
    return _out(c)


def update_container(ctx: RequestContext, container_id: uuid.UUID, data: ContainerUpdateIn) -> ContainerOut:
    _tenant_wide(ctx)
    c = lock(Container.objects.all(), container_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(c, field, value)
    c.save()
    return _out(c)


def set_availability(ctx: RequestContext, container_id: uuid.UUID, data: AvailabilityIn) -> ContainerOut:
    """Manual availability changes. ``in_use`` is set only by shipments; ``retired`` is terminal."""
    _tenant_wide(ctx)
    c = lock(Container.objects.all(), container_id)
    assert_state(c.availability, ("available", "maintenance"), f"set availability to {data.availability}")
    previous = c.availability
    c.availability = data.availability
    c.save(update_fields=["availability", "updated_at"])
    ContainerEvent.for_context(
        container=c,
        kind=ContainerEvent.Kind.STATUS,
        note=f"{previous} -> {data.availability}. {data.reason}".strip(),
        actor_user_id=ctx.user_id,
    ).save()
    return _out(c)


def record_inspection(ctx: RequestContext, container_id: uuid.UUID, data: InspectionIn) -> ContainerOut:
    _tenant_wide(ctx)
    c = lock(Container.objects.all(), container_id)
    c.condition = data.condition
    c.save(update_fields=["condition", "updated_at"])
    ContainerEvent.for_context(
        container=c,
        kind=ContainerEvent.Kind.INSPECTION,
        condition=data.condition,
        location_label=data.location_label,
        note=data.note,
        actor_user_id=ctx.user_id,
    ).save()
    return _out(c)


def list_events(ctx: RequestContext, container_id: uuid.UUID) -> list[ContainerEventOut]:
    _tenant_wide(ctx)
    if not Container.objects.filter(id=container_id).exists():
        raise not_found()
    return [
        ContainerEventOut.model_validate(e, from_attributes=True)
        for e in ContainerEvent.objects.filter(container_id=container_id).order_by("id")
    ]


# ---------------------------------------------------------------- used by shipments


def reserve(container_ids: list[uuid.UUID], *, actor_user_id: uuid.UUID | None, shipment_ref: str) -> None:
    """Mark containers in use by a shipment. All must exist and be available (else 409/404)."""
    rows = list(Container.objects.select_for_update().filter(id__in=container_ids))
    if len(rows) != len(set(container_ids)):
        raise not_found("One or more containers were not found.")
    for c in rows:
        rule(
            c.availability == Container.Availability.AVAILABLE,
            "container_unavailable",
            f"Container {c.number} is not available ({c.availability}).",
            {"container_id": str(c.id), "availability": c.availability},
        )
    for c in rows:
        c.availability = Container.Availability.IN_USE
        c.save(update_fields=["availability", "updated_at"])
        ContainerEvent.for_context(
            container=c,
            kind=ContainerEvent.Kind.MOVEMENT,
            note=f"Loaded on shipment {shipment_ref}",
            actor_user_id=actor_user_id,
        ).save()


def release(container_ids: list[uuid.UUID], *, actor_user_id: uuid.UUID | None, shipment_ref: str) -> None:
    for c in Container.objects.select_for_update().filter(id__in=container_ids):
        if c.availability == Container.Availability.IN_USE:
            c.availability = Container.Availability.AVAILABLE
            c.save(update_fields=["availability", "updated_at"])
        ContainerEvent.for_context(
            container=c,
            kind=ContainerEvent.Kind.MOVEMENT,
            note=f"Released from shipment {shipment_ref}",
            actor_user_id=actor_user_id,
        ).save()


def numbers(container_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    return dict(Container.objects.filter(id__in=container_ids).values_list("id", "number"))
