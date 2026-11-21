"""tracking Celery tasks: partition maintenance and retention (MASTER_PROMPT §2, §4.1; D-058).

Runs on the ``relay`` connection (role corridor_relay), which may only call the gps_* maintenance
functions, so this job cannot read or change anything else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import structlog
from celery import shared_task
from django.conf import settings
from django.db import connections, transaction

from corridor.tracking.archive import get_archive

log = structlog.get_logger(__name__)
DB = "relay"


@dataclass
class MaintenanceReport:
    partitions_created: int = 0
    archived: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    pending_approval: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _call(sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    with transaction.atomic(using=DB), connections[DB].cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def run_maintenance(*, drop_enabled: bool | None = None) -> MaintenanceReport:
    keep = int(settings.GPS_RETENTION_MONTHS)
    drop = settings.GPS_RETENTION_DROP_ENABLED if drop_enabled is None else drop_enabled
    report = MaintenanceReport()
    report.partitions_created = int(_call("SELECT gps_ensure_partitions(%s, %s)", [keep, 3])[0][0])

    cutoff: date = _call("SELECT gps_retention_cutoff(%s)", [keep])[0][0]
    expired = [
        name for name, month in _call("SELECT name, month_start FROM gps_partitions()", []) if month < cutoff
    ]
    archive = get_archive()
    for name in expired:
        try:
            rows = [r[0] for r in _call("SELECT * FROM gps_partition_export(%s, %s)", [name, keep])]
            receipt = archive.write(name, rows)
            if not archive.verify(receipt):
                raise RuntimeError("archive verification failed")
            report.archived.append(name)
            if drop:
                _call("SELECT gps_drop_partition(%s, %s)", [name, keep])
                report.dropped.append(name)
                log.info("gps_partition_dropped", partition=name, rows=receipt.rows, sha256=receipt.sha256)
            else:
                # Dropping deletes data: it needs explicit approval in production (MASTER_PROMPT §0.3).
                report.pending_approval.append(name)
                log.warning("gps_partition_drop_pending_approval", partition=name, rows=receipt.rows)
        except Exception:
            log.exception("gps_retention_failed", partition=name)
            report.failed.append(name)
    log.info("gps_maintenance", **report.__dict__)
    return report


@shared_task(name="corridor.tracking.tasks.gps_maintenance")
def gps_maintenance() -> dict[str, Any]:
    return run_maintenance().__dict__
