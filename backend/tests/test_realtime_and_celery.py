from __future__ import annotations

import pytest
import structlog
from channels.testing import WebsocketCommunicator

from config.asgi import application
from config.celery import _propagate_request_id
from corridor.events.tasks import heartbeat


async def test_websocket_ping_pong() -> None:
    communicator = WebsocketCommunicator(application, "/ws/v1/ping/")
    connected, _ = await communicator.connect()
    assert connected
    await communicator.send_json_to({"type": "ping"})
    assert await communicator.receive_json_from() == {"type": "pong"}
    await communicator.send_json_to({"type": "subscribe", "topic": "fleet"})
    assert (await communicator.receive_json_from())["type"] == "error"
    await communicator.disconnect()


async def test_unknown_websocket_path_is_rejected() -> None:
    communicator = WebsocketCommunicator(application, "/ws/v1/tracking/")
    with pytest.raises(ValueError, match="No route found"):
        await communicator.connect()


def test_heartbeat_task_runs() -> None:
    assert heartbeat.delay().get() == "ok"


def test_request_id_is_propagated_into_task_headers() -> None:
    structlog.contextvars.bind_contextvars(request_id="publish-corr-0001")
    try:
        headers: dict[str, str] = {}
        _propagate_request_id(headers=headers)
    finally:
        structlog.contextvars.clear_contextvars()
    assert headers["request_id"] == "publish-corr-0001"


def test_request_id_generated_when_publishing_outside_a_request() -> None:
    headers: dict[str, str] = {}
    _propagate_request_id(headers=headers)
    assert len(headers["request_id"]) == 32
