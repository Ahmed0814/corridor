"""Redis-backed fixed-window rate limiting (MASTER_PROMPT §5 "rate limiting (Redis-backed)").

Used for public endpoints (tracking links) per client IP. If Redis is unreachable the limiter fails
OPEN (logs a warning): availability of tracking pages matters more than a perfect limit, and the WAF
rate rules in front of the ALB remain the outer limit in AWS (security-model.md §8).
"""

from __future__ import annotations

import time

import redis
import structlog
from django.conf import settings

from corridor.core.api import ApiError

log = structlog.get_logger(__name__)
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)
    return _client


def check(bucket: str, key: str, *, limit: int, window_seconds: int = 60) -> None:
    """Raise 429 when `key` exceeded `limit` requests in the current window of `bucket`."""
    window = int(time.time() // window_seconds)
    name = f"rl:{bucket}:{key}:{window}"
    try:
        pipe = _redis().pipeline()
        pipe.incr(name)
        pipe.expire(name, window_seconds + 5)
        count = int(pipe.execute()[0])
    except redis.RedisError:
        log.warning("rate_limit_unavailable", bucket=bucket)
        return
    if count > limit:
        raise ApiError(
            429,
            "rate_limited",
            "Too many requests. Try again shortly.",
            {"retry_after_seconds": window_seconds},
        )
