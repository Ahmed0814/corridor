"""Celery tasks and WebSocket consumers respect tenant context (Phase 2 DoD)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from channels.testing import WebsocketCommunicator

from config.asgi import application
from corridor.core.tasks import tenant_task
from corridor.core.tenancy import TenantContextError, current_tenant_id
from corridor.identity.models import TenantMembership
from corridor.identity.permissions import ClientKind
from corridor.realtime import consumers
from corridor.realtime.services import broadcast_fleet, fleet_group
from tests.support import World, token_for


@tenant_task(name="tests.count_memberships")
def count_memberships() -> dict[str, object]:
    return {
        "context": str(current_tenant_id()),
        "tenants": sorted({str(t) for t in TenantMembership.objects.values_list("tenant_id", flat=True)}),
        "count": TenantMembership.objects.count(),
    }


@pytest.mark.django_db
def test_tenant_task_sees_only_its_tenant(world: World) -> None:
    alpha, bravo = world.tenants["alpha"], world.tenants["bravo"]
    a = count_memberships.delay(str(alpha)).get()
    b = count_memberships.delay(str(bravo)).get()
    assert a["tenants"] == [str(alpha)] and a["context"] == str(alpha)
    assert b["tenants"] == [str(bravo)] and b["context"] == str(bravo)
    assert a["count"] > 0 and b["count"] > 0
    # The context does not leak out of the task.
    assert current_tenant_id() is None


@pytest.mark.django_db
def test_tenant_task_refuses_a_missing_or_malformed_tenant(world: World) -> None:
    with pytest.raises(ValueError):
        count_memberships.delay("not-a-uuid").get()
    with pytest.raises(TypeError):
        count_memberships.delay().get()


@pytest.mark.django_db
def test_tenant_task_for_unknown_tenant_sees_nothing(world: World) -> None:
    assert count_memberships.delay(str(uuid.uuid4())).get()["count"] == 0


@pytest.mark.django_db
def test_plain_code_outside_a_task_context_cannot_query_tenant_data(world: World) -> None:
    with pytest.raises(TenantContextError):
        TenantMembership.objects.count()


# --------------------------------------------------------------------------- WebSocket
# The consumer authenticates on its own DB connection (another thread), so these tests use the
# committed fixture world.


async def _connect(origin: str | None = None) -> WebsocketCommunicator:
    headers = [(b"origin", origin.encode())] if origin else []
    communicator = WebsocketCommunicator(application, "/ws/v1/tracking/", headers=headers)
    connected, _ = await communicator.connect()
    assert connected
    return communicator


async def _auth(comm: WebsocketCommunicator, token: str, tenant: str | None = None) -> dict[str, object]:
    message: dict[str, object] = {"action": "auth", "token": token}
    if tenant:
        message["tenant"] = tenant
    await comm.send_json_to(message)
    return await comm.receive_output(timeout=5)  # type: ignore[no-any-return]


@pytest.mark.django_db
async def test_fleet_subscription_is_limited_to_own_tenant(world: World) -> None:
    alpha_ws = await _connect()
    reply = await _auth(alpha_ws, token_for("dispatcher@alpha.test"))
    assert reply["type"] == "websocket.send"
    await alpha_ws.send_json_to({"action": "subscribe", "topic": "fleet"})
    assert await alpha_ws.receive_json_from(timeout=5) == {"type": "subscribed", "topic": "fleet"}

    await asyncio.to_thread(broadcast_fleet, world.tenants["bravo"], {"vehicle": "bravo-truck"})
    assert await alpha_ws.receive_nothing(timeout=0.3)
    await asyncio.to_thread(broadcast_fleet, world.tenants["alpha"], {"vehicle": "alpha-truck"})
    assert await alpha_ws.receive_json_from(timeout=5) == {
        "type": "fleet.update",
        "data": {"vehicle": "alpha-truck"},
    }
    await alpha_ws.disconnect()


@pytest.mark.django_db
async def test_cannot_authenticate_into_another_tenant(world: World) -> None:
    ws = await _connect()
    reply = await _auth(ws, token_for("dispatcher@bravo.test"), tenant="alpha")
    assert reply == {"type": "websocket.close", "code": consumers.CLOSE_FORBIDDEN}


@pytest.mark.django_db
async def test_driver_and_customer_cannot_subscribe_to_the_fleet(world: World) -> None:
    for identifier, client in (
        ("+25377000001", ClientKind.DRIVER_MOBILE),
        ("customer@alpha.test", ClientKind.WEB_PORTAL),
    ):
        ws = await _connect()
        reply = await _auth(ws, token_for(identifier, client))
        assert reply["type"] == "websocket.send", identifier
        await ws.send_json_to({"action": "subscribe", "topic": "fleet"})
        assert await ws.receive_json_from(timeout=5) == {"type": "error", "code": "not_found"}
        await ws.disconnect()


@pytest.mark.django_db
async def test_client_cannot_name_a_group(world: World) -> None:
    ws = await _connect()
    await _auth(ws, token_for("dispatcher@alpha.test"))
    await ws.send_json_to({"action": "subscribe", "topic": fleet_group(world.tenants["bravo"])})
    assert await ws.receive_json_from(timeout=5) == {"type": "error", "code": "not_found"}
    await ws.send_json_to({"action": "subscribe", "topic": "shipment", "id": str(uuid.uuid4())})
    assert await ws.receive_json_from(timeout=5) == {"type": "error", "code": "not_found"}
    await ws.disconnect()


@pytest.mark.django_db
async def test_first_message_must_authenticate(world: World) -> None:
    ws = await _connect()
    await ws.send_json_to({"action": "subscribe", "topic": "fleet"})
    assert await ws.receive_output(timeout=5) == {
        "type": "websocket.close",
        "code": consumers.CLOSE_UNAUTHENTICATED,
    }


@pytest.mark.django_db
async def test_invalid_token_closes_the_socket(world: World) -> None:
    ws = await _connect()
    assert await _auth(ws, "garbage") == {"type": "websocket.close", "code": consumers.CLOSE_UNAUTHENTICATED}


@pytest.mark.django_db
async def test_suspended_tenant_cannot_connect(world: World) -> None:
    ws = await _connect()
    reply = await _auth(ws, token_for("dispatcher@charlie.test"))
    assert reply == {"type": "websocket.close", "code": consumers.CLOSE_FORBIDDEN}


async def test_unauthenticated_socket_is_closed_after_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(consumers, "AUTH_TIMEOUT_SECONDS", 0.2)
    ws = await _connect()
    assert await ws.receive_output(timeout=3) == {
        "type": "websocket.close",
        "code": consumers.CLOSE_UNAUTHENTICATED,
    }


async def test_foreign_browser_origin_is_rejected() -> None:
    communicator = WebsocketCommunicator(
        application, "/ws/v1/tracking/", headers=[(b"origin", b"https://evil.example")]
    )
    connected, code = await communicator.connect()
    assert not connected and code == consumers.CLOSE_FORBIDDEN


@pytest.mark.django_db
async def test_allowed_origin_and_token_in_query_string_is_ignored(world: World) -> None:
    token = token_for("dispatcher@alpha.test")
    communicator = WebsocketCommunicator(
        application, f"/ws/v1/tracking/?token={token}", headers=[(b"origin", b"http://localhost:3000")]
    )
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"action": "subscribe", "topic": "fleet"})
    assert await communicator.receive_output(timeout=5) == {
        "type": "websocket.close",
        "code": consumers.CLOSE_UNAUTHENTICATED,
    }
