"""HTTP middleware: correlation id and structured access log (sync and async capable)."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest, HttpResponseBase

from corridor.core.request_context import REQUEST_ID_HEADER, accept_or_generate, bind_request_id

log = structlog.get_logger("corridor.access")

Handler = Callable[[HttpRequest], Any]


def _start(request: HttpRequest) -> str:
    structlog.contextvars.clear_contextvars()
    request_id = accept_or_generate(request.headers.get(REQUEST_ID_HEADER))
    request.request_id = request_id  # type: ignore[attr-defined]
    bind_request_id(request_id)
    return request_id


def request_id_middleware(get_response: Handler) -> Handler:
    """Outermost middleware: binds request_id into log context and echoes it in the response."""
    if iscoroutinefunction(get_response):

        async def amiddleware(request: HttpRequest) -> HttpResponseBase:
            request_id = _start(request)
            response: HttpResponseBase = await get_response(request)
            response[REQUEST_ID_HEADER] = request_id
            return response

        markcoroutinefunction(amiddleware)
        return amiddleware

    def middleware(request: HttpRequest) -> HttpResponseBase:
        request_id = _start(request)
        response: HttpResponseBase = get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response

    return middleware


def _log_access(request: HttpRequest, response: HttpResponseBase, started: float) -> None:
    if request.path.startswith("/healthz/live"):
        return  # container probes every few seconds; not worth a line
    log.info(
        "http_request",
        method=request.method,
        path=request.path,
        status=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )


def access_log_middleware(get_response: Handler) -> Handler:
    if iscoroutinefunction(get_response):

        async def amiddleware(request: HttpRequest) -> HttpResponseBase:
            started = time.perf_counter()
            response: HttpResponseBase = await get_response(request)
            _log_access(request, response, started)
            return response

        markcoroutinefunction(amiddleware)
        return amiddleware

    def middleware(request: HttpRequest) -> HttpResponseBase:
        started = time.perf_counter()
        response: HttpResponseBase = get_response(request)
        _log_access(request, response, started)
        return response

    return middleware


AsyncHandler = Callable[[HttpRequest], Awaitable[HttpResponseBase]]
