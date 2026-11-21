from __future__ import annotations

import structlog
from celery import shared_task

log = structlog.get_logger(__name__)


@shared_task(name="corridor.events.tasks.heartbeat")
def heartbeat() -> str:
    """Scheduled by beat every 60 s; proves the scheduler → broker → worker path."""
    log.info("celery_heartbeat")
    return "ok"
