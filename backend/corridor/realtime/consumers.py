from __future__ import annotations

from typing import Any

import structlog
from channels.generic.websocket import AsyncJsonWebsocketConsumer

log = structlog.get_logger(__name__)


class PingConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Answers {"type": "ping"} with {"type": "pong"}. No tenant data, no groups."""

    async def connect(self) -> None:
        await self.accept()

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})
        else:
            await self.send_json({"type": "error", "code": "unsupported_message"})
