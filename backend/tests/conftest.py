from __future__ import annotations

import os

import pytest
import redis
from django.conf import settings


def _redis_reachable() -> bool:
    try:
        return bool(redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1).ping())
    except Exception:
        return False


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`requires_redis` tests skip locally when Redis is absent, but abort the run in CI.

    CI sets REQUIRE_SERVICES=1 so a missing service can never become a silent pass
    (MASTER_PROMPT §0.2: never mark a test as passing unless it ran and passed).
    """
    needs_redis = [item for item in items if "requires_redis" in item.keywords]
    if not needs_redis or _redis_reachable():
        return
    if os.environ.get("REQUIRE_SERVICES") == "1":
        raise pytest.UsageError(f"REQUIRE_SERVICES=1 but Redis at {settings.REDIS_URL} is unreachable")
    skip = pytest.mark.skip(reason="Redis not reachable locally (runs in CI with REQUIRE_SERVICES=1)")
    for item in needs_redis:
        item.add_marker(skip)
