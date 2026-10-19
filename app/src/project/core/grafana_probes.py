"""Small, scheduled queries through Grafana's actual PostgreSQL data source."""

import time

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from project.core import grafana_contact
from project.core.models import MonitoringResult
from project.core.monitoring import record_task_success


@shared_task(time_limit=240, soft_time_limit=230)
def run_grafana_probes() -> None:
    # A small fixed inventory bounds runtime and metrics cardinality. Token is never logged.
    netuids = settings.SENTINEL_GRAFANA_PROBE_NETUIDS
    if not grafana_contact.probes_configured():
        return
    checks = [("connection", "all", "SELECT 1 AS value")]
    for netuid in sorted(set(netuids)):
        checks.extend(
            [
                (
                    "snapshots",
                    str(netuid),
                    f"SELECT block_id AS value FROM metagraph_dump WHERE netuid = {int(netuid)} "  # noqa: S608 -- integer only
                    "AND finished_at IS NOT NULL ORDER BY block_id DESC LIMIT 1",
                ),
                (
                    "apy",
                    str(netuid),
                    f"SELECT apy_pct AS value FROM metagraph_validator_apy_epoch WHERE subnet_id = {int(netuid)} "  # noqa: S608 -- integer only
                    "AND epoch_ts IS NOT NULL ORDER BY epoch_ts DESC LIMIT 1",
                ),
            ]
        )
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_xact_lock(1936614773)")
            if not cursor.fetchone()[0]:
                return
        source = grafana_contact.contact()
        results = []
        for name, netuid, sql in checks:
            started = time.monotonic()
            result = source.query(sql)
            results.append(
                MonitoringResult(
                    kind="query",
                    name=name,
                    netuid=netuid,
                    checked_at=timezone.now(),
                    duration_seconds=time.monotonic() - started,
                    success=not result.error and result.rows > 0,
                    error_code=result.error or ("no_data" if result.rows == 0 else ""),
                )
            )
        MonitoringResult.objects.filter(kind="query").delete()
        MonitoringResult.objects.bulk_create(results)
        # Completion, including an observed failure, is distinct from query success.
        record_task_success("grafana_probes")
