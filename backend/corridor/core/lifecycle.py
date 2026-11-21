"""Shared helpers for explicit state transitions (MASTER_PROMPT §4.3, docs/architecture/state-machines.md).

Every transition is a service function that:
  1. locks the row (``select_for_update``) through the tenant-scoped manager (missing -> 404),
  2. checks the current state is an allowed source (else 409 ``invalid_transition``),
  3. checks business rules and permission, then
  4. updates the state and appends an immutable event in the same transaction.
There is no generic "set status" operation anywhere.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from django.db import models

from corridor.core.api import ApiError


class ActorKind(StrEnum):
    USER = "user"
    SYSTEM = "system"
    INTEGRATION = "integration"


def not_found(what: str = "Not found.") -> ApiError:
    return ApiError(404, "not_found", what)


def lock[M: models.Model](queryset: models.QuerySet[M], pk: Any) -> M:
    """Lock one row of a tenant-scoped queryset for the rest of the transaction, or 404."""
    obj = queryset.select_for_update().filter(pk=pk).first()
    if obj is None:
        raise not_found()
    return obj


def assert_state(current: str, allowed: Iterable[str], action: str) -> None:
    allowed = tuple(allowed)
    if current not in allowed:
        raise ApiError(
            409,
            "invalid_transition",
            f"Cannot {action} from status '{current}'.",
            {"status": current, "allowed_from": list(allowed), "action": action},
        )


def rule(condition: bool, code: str, message: str, details: Any = None) -> None:
    """A business rule that must hold for the transition (409 with a specific code)."""
    if not condition:
        raise ApiError(409, code, message, details)


def require_reason(reason: str | None) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ApiError(422, "reason_required", "A reason is required for this action.")
    return reason
