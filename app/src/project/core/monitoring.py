"""Persist and evaluate data progress without scanning large tables on scrape."""

from datetime import datetime

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from apps.metagraph.models import MetagraphDump, Subnet, ValidatorApyEpoch
from project.core.models import MonitoringProgress, MonitoringResult


def record_task_success(name: str) -> None:
    MonitoringProgress.objects.update_or_create(name=name, defaults={"succeeded_at": timezone.now()})


@transaction.atomic
def record_ingestion_success(name: str, block: int, source_timestamp: datetime | None) -> None:
    progress, _ = MonitoringProgress.objects.select_for_update().get_or_create(
        name=name, defaults={"succeeded_at": timezone.now()}
    )
    # A replay may complete today but still describe yesterday's chain state.
    if block >= progress.source_block:
        progress.source_block = block
        progress.source_timestamp = source_timestamp
    progress.succeeded_at = timezone.now()
    progress.save()


@shared_task(time_limit=240, soft_time_limit=230)
def refresh_data_health() -> None:
    now = timezone.now()
    results = []

    def add(name, netuid, stamp, age):
        results.append(
            MonitoringResult(
                kind="data",
                name=name,
                netuid=str(netuid),
                checked_at=now,
                source_timestamp=stamp,
                max_age_seconds=age,
                success=stamp is not None,
            )
        )

    # A failed refresh keeps its previous completion time. No partial batch is published.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SELECT pg_try_advisory_xact_lock(1936614772)")
            if not cursor.fetchone()[0]:
                return
        subnets = dict(Subnet.objects.values_list("netuid", "tempo"))
        netuids = settings.METAGRAPH_NETUIDS or sorted(subnets)
        for netuid in netuids:
            age = 2 * (subnets.get(netuid, 360) or 360) * settings.BITTENSOR_SECONDS_PER_BLOCK
            age += 2 * settings.BITTENSOR_SECONDS_PER_BLOCK + 600
            stamp = (
                MetagraphDump.objects.filter(netuid=netuid, finished_at__isnull=False)
                .order_by("-block_id")
                .values_list("block__timestamp", flat=True)
                .first()
            )
            add("snapshots", netuid, stamp, age)
            apy_stamp = (
                ValidatorApyEpoch.objects.filter(subnet_id=netuid, epoch_ts__isnull=False)
                .order_by("-epoch_ts")
                .values_list("epoch_ts", flat=True)
                .first()
            )
            add("apy", netuid, apy_stamp, age + 1800)
        progress = MonitoringProgress.objects.filter(name="extrinsics").first()
        add("extrinsics", "all", progress.source_timestamp if progress else None, 300)
        MonitoringResult.objects.filter(kind="data").delete()
        MonitoringResult.objects.bulk_create(results)
        record_task_success("data_health")
