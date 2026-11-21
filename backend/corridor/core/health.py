"""Infrastructure health endpoints (business health arrives with tracking, Phase 4)."""

from __future__ import annotations

import redis
import structlog
from django.conf import settings
from django.db import connection, transaction
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

log = structlog.get_logger(__name__)


@transaction.non_atomic_requests
@require_GET
def live(request: HttpRequest) -> JsonResponse:
    """Process is up. Never touches dependencies (used by ECS container health)."""
    return JsonResponse({"status": "ok"})


def check_database() -> bool:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            return row is not None and row[0] == 1
    except Exception:
        log.warning("readiness_database_failed", exc_info=True)
        return False


def check_redis() -> bool:
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
        return bool(client.ping())
    except Exception:
        log.warning("readiness_redis_failed", exc_info=True)
        return False


@transaction.non_atomic_requests
@require_GET
def ready(request: HttpRequest) -> JsonResponse:
    """Dependencies reachable (used by the ALB target group)."""
    checks = {"database": check_database(), "redis": check_redis()}
    ok = all(checks.values())
    return JsonResponse(
        {"status": "ok" if ok else "unavailable", "checks": checks}, status=200 if ok else 503
    )
