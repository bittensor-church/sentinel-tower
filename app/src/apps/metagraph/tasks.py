"""Celery tasks for the metagraph app.

`refresh_validator_apy_windows` is run by Celery beat every 15 minutes (see
CELERY_BEAT_SCHEDULE in project/settings.py) to refresh the materialized views
that back the validator-APY dashboard: `mv_validator_apy_windows` (rolling
time-window APY) and `mv_subnet_validator_apy_epochs` (per-epoch APY).
The full rebuild takes ~2.5 min on prod, well under the 10-minute task time
limit set on the decorator.

CONCURRENTLY keeps the dashboard readable while refreshing; it requires the
unique index created in migration 0008 (mv_validator_apy_windows) and the
unique index on (subnet_id, neuron_id, epoch_block) for
mv_subnet_validator_apy_epochs.
"""

from datetime import timedelta

import structlog
from celery import shared_task
from django.db import connection

logger = structlog.get_logger()

REFRESH_TIME_LIMIT = int(timedelta(minutes=10).total_seconds())


@shared_task(time_limit=REFRESH_TIME_LIMIT, soft_time_limit=REFRESH_TIME_LIMIT - 30)
def refresh_validator_apy_windows() -> None:
    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_validator_apy_windows;")
        cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_subnet_validator_apy_epochs;")
    logger.info("Refreshed mv_validator_apy_windows and mv_subnet_validator_apy_epochs")
