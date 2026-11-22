"""Idempotency-Key handling for state-changing endpoints (MASTER_PROMPT §4.3/§5, DECISIONS D-015).

    @router.post("/shipments/{shipment_id}/dispatch", response=ShipmentOut)
    @requires("shipments.dispatch")
    @idempotent
    def dispatch(request, shipment_id): ...

* The header is required (400 ``idempotency_key_required``).
* Scope: (tenant, user, key). The request fingerprint is SHA-256 of method, path and body.
* Same key + same fingerprint -> the stored response is replayed (no second side effect).
* Same key + different fingerprint -> 422 ``idempotency_key_reused``.
* Concurrent duplicates: the row is inserted *before* the action runs; the second request blocks
  on the unique index until the first commits, then replays. If the first fails, its transaction
  (and the row) roll back, so the key can be retried.
* Error responses are not stored: they roll back the request transaction (D-045).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta
from functools import wraps
from typing import Any

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.http.request import RawPostDataException
from django.utils import timezone
from ninja.responses import NinjaJSONEncoder, Status

from corridor.core.api import ApiError, api
from corridor.core.models import IdempotencyKey
from corridor.core.tenancy import require_tenant_id

HEADER = "Idempotency-Key"
TTL = timedelta(hours=24)
_VALID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _fingerprint(request: HttpRequest) -> str:
    h = hashlib.sha256()
    h.update(request.method.encode() if request.method else b"")
    h.update(b"\0")
    h.update(request.path.encode())
    h.update(b"\0")
    try:
        h.update(request.body or b"")
    except RawPostDataException:
        # multipart uploads: the stream was already parsed into POST/FILES, so fingerprint those
        # (form fields plus each file's name and content hash) instead of the raw body.
        for key in sorted(request.POST):
            h.update(f"{key}={request.POST.getlist(key)}".encode())
            h.update(b"\0")
        for key in sorted(request.FILES):
            for f in request.FILES.getlist(key):
                digest = hashlib.sha256()
                for chunk in f.chunks():
                    digest.update(chunk)
                f.seek(0)
                h.update(f"{key}:{f.name}:{digest.hexdigest()}".encode())
                h.update(b"\0")
    return h.hexdigest()


def _serialise(result: Any) -> tuple[int, Any]:
    """Status and JSON body exactly as Ninja renders them, so a replay is byte-identical."""
    status, value = 200, result
    if isinstance(result, Status):
        status, value = result.status_code, result.value
    elif isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], int):
        status, value = result
    body: Any = json.loads(json.dumps(value, cls=NinjaJSONEncoder))
    return status, body


def _replay(request: HttpRequest, row: IdempotencyKey, fingerprint: str) -> HttpResponse:
    if row.request_hash != fingerprint:
        raise ApiError(
            422, "idempotency_key_reused", "This Idempotency-Key was already used for a different request."
        )
    response = api.create_response(request, row.response_body, status=row.response_status)
    response["Idempotent-Replayed"] = "true"
    return response


def idempotent[F: Callable[..., Any]](fn: F) -> F:
    @wraps(fn)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
        key = request.headers.get(HEADER, "")
        if not key:
            raise ApiError(400, "idempotency_key_required", f"The {HEADER} header is required.")
        if not _VALID.fullmatch(key):
            raise ApiError(400, "bad_request", f"Invalid {HEADER} (8-128 chars of A-Z a-z 0-9 . _ : -).")
        ctx = getattr(request, "auth", None)
        user_id = getattr(ctx, "user_id", None)
        if user_id is None:
            raise ApiError(401, "unauthenticated", "Authentication required.")
        tenant_id = require_tenant_id()
        fingerprint = _fingerprint(request)

        existing = (
            IdempotencyKey.objects.select_for_update()
            .filter(user_id=user_id, key=key, expires_at__gt=timezone.now())
            .first()
        )
        if existing is not None and existing.response_status:
            return _replay(request, existing, fingerprint)
        if existing is None:
            # Expired rows with the same key are removed so the unique index does not block reuse.
            IdempotencyKey.objects.filter(user_id=user_id, key=key, expires_at__lte=timezone.now()).delete()
            try:
                with transaction.atomic():
                    existing = IdempotencyKey.objects.create(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        key=key,
                        method=request.method or "",
                        path=request.path[:300],
                        request_hash=fingerprint,
                        expires_at=timezone.now() + TTL,
                    )
            except IntegrityError:
                # A concurrent request with this key committed first (we waited on its lock).
                row = IdempotencyKey.objects.filter(user_id=user_id, key=key).first()
                if row is None or not row.response_status:
                    raise ApiError(
                        409, "conflict", "A request with this Idempotency-Key is in progress."
                    ) from None
                return _replay(request, row, fingerprint)
        elif existing.request_hash != fingerprint:
            raise ApiError(
                422,
                "idempotency_key_reused",
                "This Idempotency-Key was already used for a different request.",
            )

        result = fn(request, *args, **kwargs)
        if isinstance(result, HttpResponse):
            return result
        status, body = _serialise(result)
        existing.response_status = status
        existing.response_body = body
        existing.save(update_fields=["response_status", "response_body"])
        return result

    return wrapper  # type: ignore[return-value]


def purge_expired() -> int:
    """Delete expired keys of the current tenant (scheduled per tenant by beat)."""
    deleted, _ = IdempotencyKey.objects.filter(expires_at__lte=timezone.now()).delete()
    return deleted
