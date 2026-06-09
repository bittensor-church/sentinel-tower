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
from django.db import connection

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
