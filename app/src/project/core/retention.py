"""Cross-app retention orchestrator.

Computes one cutoff block number (the newest block older than the retention
window — blocks are the shared clock for both apps) and runs each app's
``prune_expired``. Serialised via a Postgres advisory lock held for the whole
run, so the daily beat task and a manually-run ``prune_retention`` command
cannot overlap; this also defuses Celery redelivery of long-running tasks
(acks_late is enabled globally). Both supported entry points (the management
command and the beat task) MUST go through :func:`run` — never call the
per-app ``prune_expired`` functions directly in production code.
"""

from datetime import timedelta

import structlog
from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.extrinsics import retention as extrinsics_retention
from apps.metagraph import retention as metagraph_retention
from apps.metagraph.models import Block

logger = structlog.get_logger()

# Arbitrary constant identifying the retention advisory lock ("RETN").
RETENTION_LOCK_KEY = 0x5245544E


def _try_advisory_lock(cursor) -> bool:
    cursor.execute("SELECT pg_try_advisory_lock(%s)", [RETENTION_LOCK_KEY])
    return bool(cursor.fetchone()[0])


def compute_cutoff_block(days: int) -> int | None:
    """Newest block number strictly older than the retention window, or None."""
    boundary = timezone.now() - timedelta(days=days)
    return (
        Block.objects.filter(timestamp__isnull=False, timestamp__lt=boundary)
        .order_by("-number")
        .values_list("number", flat=True)
        .first()
    )


def run(
    days: int | None = None,
    batch_size: int | None = None,
    dry_run: bool = False,
    max_batches: int | None = None,
) -> dict:
    """Compute the cutoff and prune both apps. Returns cutoff + per-table counts."""
    days = days if days is not None else settings.DATA_RETENTION_DAYS

    with connection.cursor() as cursor:
        if not _try_advisory_lock(cursor):
            logger.info("Retention run already in progress; skipping")
            return {"cutoff_block": None, "deleted": {}, "skipped": "lock"}
        try:
            cutoff_block = compute_cutoff_block(days)
            if cutoff_block is None:
                logger.info("Retention run found nothing older than window", days=days)
                return {"cutoff_block": None, "deleted": {}}

            logger.info("Retention run starting", days=days, cutoff_block=cutoff_block, dry_run=dry_run)
            deleted: dict[str, int] = {}
            for prune in (metagraph_retention.prune_expired, extrinsics_retention.prune_expired):
                deleted |= prune(
                    cutoff_block=cutoff_block,
                    batch_size=batch_size,
                    dry_run=dry_run,
                    max_batches=max_batches,
                )
            logger.info("Retention run finished", cutoff_block=cutoff_block, dry_run=dry_run, **deleted)
            return {"cutoff_block": cutoff_block, "deleted": deleted}
        finally:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [RETENTION_LOCK_KEY])
