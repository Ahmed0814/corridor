"""The single versioned Ninja API (/api/v1) and its uniform error envelope.

Error format (MASTER_PROMPT §5):
    {"error": {"code": str, "message": str, "details": any, "request_id": str | None}}
"""

from __future__ import annotations

from typing import Any

import structlog
from django.db import connections, transaction
from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from corridor.core.request_context import current_request_id

log = structlog.get_logger(__name__)

api = NinjaAPI(
    title="Corridor API",
    version="1.0.0",
    urls_namespace="api-v1",
    description="Multi-tenant logistics, container tracking and fleet platform.",
)


class ApiError(Exception):
    """A deliberate API error with a stable machine-readable code."""

    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def _rollback_request_transaction() -> None:
    # Ninja turns exceptions into responses *inside* the ATOMIC_REQUESTS transaction, which would
    # otherwise commit partial writes made before the error. Every error response rolls back.
    if connections["default"].in_atomic_block:
        transaction.set_rollback(True)


def error_response(
    request: HttpRequest, status: int, code: str, message: str, details: Any = None
) -> HttpResponse:
    _rollback_request_transaction()
    return api.create_response(
        request,
        {
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": current_request_id(),
            }
        },
        status=status,
    )


@api.exception_handler(ApiError)
def _api_error(request: HttpRequest, exc: ApiError) -> HttpResponse:
    return error_response(request, exc.status, exc.code, exc.message, exc.details)


@api.exception_handler(ValidationError)
def _validation(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    return error_response(request, 422, "validation_error", "Request validation failed.", exc.errors)


@api.exception_handler(AuthenticationError)
def _unauthenticated(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    return error_response(request, 401, "unauthenticated", "Authentication required.")


@api.exception_handler(Http404)
def _not_found(request: HttpRequest, exc: Http404) -> HttpResponse:
    # Used for missing AND other-tenant resources alike (MASTER_PROMPT §4.4).
    return error_response(request, 404, "not_found", "Not found.")


@api.exception_handler(HttpError)
def _http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
    code = {400: "bad_request", 403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}
    return error_response(request, exc.status_code, code.get(exc.status_code, "error"), str(exc))


@api.exception_handler(Exception)
def _unhandled(request: HttpRequest, exc: Exception) -> HttpResponse:
    log.exception("unhandled_exception", path=request.path)
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: S110
        pass
    return error_response(request, 500, "internal_error", "Internal server error.")


@api.get("/meta", tags=["meta"], summary="API metadata", auth=None)
def meta(request: HttpRequest) -> dict[str, str]:
    from django.conf import settings

    return {"name": "corridor", "api_version": "v1", "release": settings.RELEASE}
