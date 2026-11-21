from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import environ
import pytest
import redis
from django.conf import settings
from django.db import connections

from tests.support import World, build_world, reset_db_context


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


# --------------------------------------------------------------------------- database
# Tests run as the real application role (MASTER_PROMPT §4.4). The test database is created and
# migrated as corridor_migrator (acting as corridor_owner, like a deployment), then every
# connection switches back to corridor_app. A test asserts current_user = corridor_app.

_WORLD: World | None = None


def _swap_credentials(user: str, password: str) -> None:
    cfg = connections["default"].settings_dict  # shared with connections in other threads
    cfg["USER"], cfg["PASSWORD"] = user, password
    connections["default"].close()


@pytest.fixture(scope="session")
def django_db_setup(
    django_test_environment: None, django_db_blocker: pytest.FixtureRequest
) -> Iterator[None]:
    from django.test.utils import setup_databases, teardown_databases

    global _WORLD
    default = connections["default"].settings_dict
    app_user, app_password = default["USER"], default["PASSWORD"]
    migrator = environ.Env.db_url_config(settings.MIGRATOR_DATABASE_URL)

    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        _swap_credentials(migrator["USER"], migrator["PASSWORD"])
        try:
            old_config = setup_databases(verbosity=0, interactive=False, serialized_aliases=set())
        finally:
            _swap_credentials(app_user, app_password)
        _WORLD = build_world()
    yield
    with django_db_blocker.unblock():  # type: ignore[attr-defined]
        connections.close_all()
        _swap_credentials(migrator["USER"], migrator["PASSWORD"])
        try:
            teardown_databases(old_config, verbosity=0)
        finally:
            _swap_credentials(app_user, app_password)


@pytest.fixture
def world(django_db_setup: None) -> World:
    assert _WORLD is not None
    return _WORLD


@pytest.fixture(autouse=True)
def _fresh_tenant_context() -> Iterator[None]:
    from corridor.core.tenancy import clear_context

    clear_context()
    yield
    clear_context()


@pytest.fixture(autouse=True)
async def _close_async_thread_connections(request: pytest.FixtureRequest) -> object:
    """Async tests reach the DB through asgiref's executor thread; close its connections so the
    test database can be dropped at the end of the session."""
    yield
    if request.node.get_closest_marker("django_db") and asyncio.iscoroutinefunction(request.function):
        from channels.db import database_sync_to_async

        await database_sync_to_async(connections.close_all)()


@pytest.fixture
def no_db_context(db: None) -> None:
    reset_db_context()
