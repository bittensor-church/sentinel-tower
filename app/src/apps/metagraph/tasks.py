"""Celery tasks for the metagraph app.

`refresh_validator_apy_windows` is run by Celery beat every 15 minutes (see
CELERY_BEAT_SCHEDULE in project/settings.py) to refresh the materialized views
that back the validator-APY dashboard: `mv_validator_apy_windows` (rolling
time-window APY) and `mv_subnet_validator_apy_epochs` (per-epoch APY).

CONCURRENTLY keeps the dashboard readable while refreshing; it requires the
unique index on each view.

Two safeguards keep the refresh healthy on the memory-constrained prod host:
  * a session-level advisory lock so overlapping beat ticks / manual runs don't
    stack — two concurrent REFRESHes of the same view block each other and pile
    up, which is how a single slow refresh snowballs into "never finishes";
  * a raised `work_mem`, because the window view aggregates ~1 month of the
    multi-GB neuron_snapshot table and the 4 MB default spills the sort to disk.
"""

from datetime import timedelta

import structlog
from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from prometheus_client import Gauge

from apps.metagraph.models import Block, NeuronSnapshot, SnapshotHealthMetric, Subnet
from apps.metagraph.utils import get_dumpable_blocks_in_range

logger = structlog.get_logger()

REFRESH_TIME_LIMIT = int(timedelta(minutes=10).total_seconds())

# Arbitrary constant identifying the advisory lock that serialises refreshes.
_REFRESH_LOCK_KEY = 0x41505957  # "APYW"
# Kept modest on purpose — the prod DB host is small (~8 GiB RAM).
_REFRESH_WORK_MEM = "256MB"


@shared_task(time_limit=REFRESH_TIME_LIMIT, soft_time_limit=REFRESH_TIME_LIMIT - 30)
def refresh_validator_apy_windows() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [_REFRESH_LOCK_KEY])
        row = cursor.fetchone()
        if not (row and row[0]):
            logger.info("apy view refresh already running; skipping this tick")
            return
        try:
            cursor.execute("SELECT set_config('work_mem', %s, false)", [_REFRESH_WORK_MEM])
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_validator_apy_windows;")
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_subnet_validator_apy_epochs;")
            logger.info("Refreshed mv_validator_apy_windows and mv_subnet_validator_apy_epochs")
        finally:
            cursor.execute("RESET work_mem")
            cursor.execute("SELECT pg_advisory_unlock(%s)", [_REFRESH_LOCK_KEY])


SNAPSHOT_HEALTH_TIME_LIMIT = int(timedelta(minutes=10).total_seconds())

# Look-back windows for snapshot-health, expressed as a count of blocks.
_SNAPSHOT_HEALTH_WINDOWS = {
    "7d": 7 * 24 * 3600 // settings.BITTENSOR_SECONDS_PER_BLOCK,
    "12d": 12 * 24 * 3600 // settings.BITTENSOR_SECONDS_PER_BLOCK,
}


missing_snapshot_blocks_gauge = Gauge(
    "metagraph_missing_snapshot_blocks",
    "Dumpable blocks with no NeuronSnapshot entries for this netuid in the look-back window",
    ["netuid", "window"],
    multiprocess_mode="max",
)


def _compute_missing_snapshot_blocks() -> dict[tuple[int, str], int]:
    """Count dumpable blocks with no NeuronSnapshot per (netuid, window).

    Mirrors the logic in apps.metagraph.utils.get_dumpable_blocks_in_range: for
    each look-back window it determines the blocks for which neuron snapshots are
    expected per netuid and verifies at least one snapshot exists for each
    expected block/netuid pair. Returns an empty mapping when no timestamped
    block exists yet.
    """
    latest_block = Block.objects.filter(timestamp__isnull=False).order_by("-number").first()
    if not latest_block:
        return {}

    netuids: list[int] = settings.METAGRAPH_NETUIDS or list(Subnet.objects.values_list("netuid", flat=True))

    end_block = latest_block.number
    # Process windows largest-first so each subnet is queried once over the widest
    # block range; the narrower windows are subsets and reuse that single result.
    windows_by_size = sorted(_SNAPSHOT_HEALTH_WINDOWS.items(), key=lambda kv: kv[1], reverse=True)
    widest_start_block = end_block - windows_by_size[0][1]

    results: dict[tuple[int, str], int] = {}
    for netuid in netuids:
        widest_dumpable = get_dumpable_blocks_in_range(widest_start_block, end_block, netuid)
        if not widest_dumpable:
            continue
        # A separate query for each subnet is necessary as querying all dumpable blocks for all
        # subnets in one query causes memory-related server issues. Since this is meant to be run
        # as a Celery task every 72 minutes, the longer runtime isn't critical.
        covered = set(
            NeuronSnapshot.objects.filter(
                block_id__in=widest_dumpable,
                neuron__subnet_id=netuid,
            )
            .values_list("block_id", flat=True)
            .distinct()
        )
        for window_name, block_delta in windows_by_size:
            # Narrow the widest dumpable set to this window's range; no extra query.
            dumpable = {block for block in widest_dumpable if block >= end_block - block_delta}
            if not dumpable:
                continue
            results[(netuid, window_name)] = len(dumpable - covered)
    return results


@shared_task(time_limit=SNAPSHOT_HEALTH_TIME_LIMIT, soft_time_limit=SNAPSHOT_HEALTH_TIME_LIMIT - 30)
def update_snapshot_health_metrics() -> None:
    """
    Recompute snapshot-health counts and persist them for the /metrics endpoint.

    The celery task does not update the metric itself as this would result in chaos on
    account of the intentionally recycled child processes (see 
    settings.CELERY_WORKER_MAX_TASKS_PER_CHILD). Instead, the health metrics are persisted to a
    database table that the Prometheus /metrics endpoint can scrape.

    Run by Celery beat (see settings.CELERY_BEAT_SCHEDULE).
    """
    results = _compute_missing_snapshot_blocks()
    with transaction.atomic():
        SnapshotHealthMetric.objects.all().delete()
        SnapshotHealthMetric.objects.bulk_create(
            [
                SnapshotHealthMetric(netuid=netuid, window=window, missing_blocks=missing)
                for (netuid, window), missing in results.items()
            ]
        )
    logger.info("Updated snapshot health metrics", rows=len(results))


def set_snapshot_health_metrics() -> None:
    """
    Populate the snapshot-health gauge from persisted rows in the SnapshotHealthMetric table.

    Clears the metric to allow Prometheus to mark subnet/window combinations that no longer exist
    as stale.
    """
    missing_snapshot_blocks_gauge.clear()
    for netuid, window, missing in SnapshotHealthMetric.objects.values_list("netuid", "window", "missing_blocks"):
        missing_snapshot_blocks_gauge.labels(netuid=str(netuid), window=window).set(missing)
