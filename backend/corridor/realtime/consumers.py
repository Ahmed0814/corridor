from __future__ import annotations

import asyncio
import time
from typing import Any, cast

import structlog
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.db import transaction

from corridor.core.api import ApiError
from corridor.identity.services import RequestContext, Scope, resolve_token
from corridor.realtime.services import fleet_group

log = structlog.get_logger(__name__)

AUTH_TIMEOUT_SECONDS = 10
RECHECK_SECONDS = 15 * 60

# Close codes (4000-4999 are application-defined).
CLOSE_UNAUTHENTICATED = 4001
CLOSE_FORBIDDEN = 4003


class PingConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Answers {"type": "ping"} with {"type": "pong"}. No tenant data, no groups."""

    async def connect(self) -> None:
        await self.accept()

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_json({"type": "error", "code": "unsupported_message"})


def _origin(scope: dict[str, Any]) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"origin":
            return str(value.decode("latin1"))
    return None


def _authenticate_sync(token: str, tenant_slug: str | None) -> RequestContext:
    # Same code path as HTTP, in its own short transaction (SET LOCAL ends with it). Later
    # database work for this socket opens its own tenant_context().
    with transaction.atomic():
        return resolve_token(token, tenant_slug=tenant_slug)


async def _authenticate(token: str, tenant_slug: str | None) -> RequestContext:
    return cast(RequestContext, await database_sync_to_async(_authenticate_sync)(token, tenant_slug))


class TrackingConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """/ws/v1/tracking/ (security-model.md §5).

    1. Browser origins must be allowlisted (non-browser clients send none). The token is never
       read from the URL (URLs end up in logs).
    2. The first message must be {"action": "auth", "token": "<access token>", "tenant": "<slug>"?}
       within 10 s, resolved exactly like an HTTP request (membership, suspension, client kind).
    3. {"action": "subscribe", "topic": "fleet"} joins the caller's own tenant fleet group, only for
       tenant-wide roles with tracking.read. Anything else gets a generic not_found.
    4. The membership is re-checked every 15 minutes; the socket closes if access was lost.
    """

    ctx: RequestContext | None = None
    token: str | None = None
    tenant_slug: str | None = None
    checked_at: float = 0.0
    groups_joined: set[str]

    async def connect(self) -> None:
        self.groups_joined = set()
        origin = _origin(self.scope)
        if origin is not None and origin not in settings.WEB_ALLOWED_ORIGINS:
            await self.close(code=CLOSE_FORBIDDEN)
            return
        await self.accept()
        self._auth_timer = asyncio.get_running_loop().call_later(
            AUTH_TIMEOUT_SECONDS, lambda: asyncio.ensure_future(self._auth_timeout())
        )

    async def _auth_timeout(self) -> None:
        if self.ctx is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)

    async def disconnect(self, code: int) -> None:
        timer = getattr(self, "_auth_timer", None)
        if timer is not None:
            timer.cancel()
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)
        self.groups_joined.clear()

    async def _error(self, code: str) -> None:
        await self.send_json({"type": "error", "code": code})

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if not isinstance(content, dict):
            await self._error("unsupported_message")
            return
        action = content.get("action")
        if self.ctx is None:
            if action != "auth" or not isinstance(content.get("token"), str):
                await self.close(code=CLOSE_UNAUTHENTICATED)
                return
            await self._do_auth(content["token"], content.get("tenant"))
            return
        if time.monotonic() - self.checked_at > RECHECK_SECONDS and not await self._recheck():
            return
        if action == "subscribe":
            await self._subscribe(content)
        else:
            await self._error("unsupported_message")

    async def _do_auth(self, token: str, tenant: Any) -> None:
        slug = tenant if isinstance(tenant, str) else None
        try:
            ctx = await _authenticate(token, slug)
        except ApiError as exc:
            log.info("ws_auth_rejected", code=exc.code)
            await self.close(code=CLOSE_UNAUTHENTICATED if exc.status == 401 else CLOSE_FORBIDDEN)
            return
        if ctx.tenant_id is None:
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.ctx, self.token, self.tenant_slug = ctx, token, slug
        self.checked_at = time.monotonic()
        await self.send_json({"type": "auth.ok", "tenant": ctx.tenant_slug, "role": ctx.role})

    async def _recheck(self) -> bool:
        if self.token is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return False
        try:
            ctx = await _authenticate(self.token, self.tenant_slug)
        except ApiError:
            ctx = None
        if ctx is None or self.ctx is None or ctx.tenant_id != self.ctx.tenant_id:
            await self.close(code=CLOSE_FORBIDDEN)
            return False
        self.ctx = ctx
        self.checked_at = time.monotonic()
        return True

    async def _subscribe(self, content: dict[str, Any]) -> None:
        if self.ctx is None or self.ctx.tenant_id is None:
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return
        topic = content.get("topic")
        if topic == "fleet" and self.ctx.has("tracking.read") and self.ctx.scope == Scope.TENANT:
            group = fleet_group(self.ctx.tenant_id)
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.add(group)
            await self.send_json({"type": "subscribed", "topic": "fleet"})
            return
        # Shipment topics arrive with tracking (Phase 4/6). Same answer for "forbidden" and
        # "does not exist", so a client cannot probe for other tenants' resources.
        await self._error("not_found")

    async def fleet_update(self, event: dict[str, Any]) -> None:
        await self.send_json({"type": "fleet.update", "data": event["payload"]})
