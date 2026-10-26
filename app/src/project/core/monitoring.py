"""Persist and evaluate data progress without scanning large tables on scrape."""

from datetime import datetime, timedelta

from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.metagraph.models import MetagraphDump, NeuronSnapshot, Subnet, ValidatorApyEpoch
from apps.metagraph.services.apy_epoch_ingest import RETENTION_DAYS
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

    def add(name, netuid, stamp, age, freshness_required=True):
        results.append(
            MonitoringResult(
                kind="data",
                name=name,
                netuid=str(netuid),
                checked_at=now,
                source_timestamp=stamp,
                max_age_seconds=age,
                success=stamp is not None,
                freshness_required=freshness_required,
                error_code="" if freshness_required else "no_eligible_validators",
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
            apy_stamp, latest_apy_block = (
                ValidatorApyEpoch.objects.filter(subnet_id=netuid, epoch_ts__isnull=False)
                .order_by("-epoch_ts")
                .values_list("epoch_ts", "epoch_block")
                .first()
            ) or (None, 0)
            required = _apy_freshness_required(netuid, latest_apy_block, now, age)
            add("apy", netuid, apy_stamp, age + 1800, required)
        progress = MonitoringProgress.objects.filter(name="extrinsics").first()
        add("extrinsics", "all", progress.source_timestamp if progress else None, 300)
        MonitoringResult.objects.filter(kind="data").delete()
        MonitoringResult.objects.bulk_create(results)
        record_task_success("data_health")


def _apy_freshness_required(netuid: int, latest_apy_block: int, now: datetime, max_age: int) -> bool:
    """Exempt only a recent, observed no-output epoch with no newer eligible backlog."""
    epoch = (
        MetagraphDump.objects.filter(netuid=netuid, epoch_position=2)
        .select_related("block")
        .order_by("-block_id")
        .first()
    )
    if not epoch or not epoch.finished_at or not epoch.block.timestamp:
        return True
    if not 0 <= (now - epoch.block.timestamp).total_seconds() <= max_age:
        return True
    snapshots = NeuronSnapshot.objects.filter(neuron__subnet_id=netuid)
    current = snapshots.filter(block_id=epoch.block_id)
    if (
        epoch.validator_snapshot_count is None
        or current.filter(is_validator=True).count() != epoch.validator_snapshot_count
    ):
        return True
    if not current.exists() or current.filter(is_validator=True, alpha_stake__gt=0).exists():
        return True
    # Do not hide an older eligible epoch still waiting for APY ingestion merely
    # because the newest epoch has zero stake. APY facts expire after 90 days;
    # retained validator snapshots older than that are not a processing backlog.
    # Untimestamped evidence remains unknown, so cannot grant an exemption.
    epoch_end = MetagraphDump.objects.filter(netuid=netuid, block_id=OuterRef("block_id"), epoch_position=2)
    return (
        snapshots.filter(
            is_validator=True,
            alpha_stake__gt=0,
            block_id__gt=latest_apy_block,
        )
        .filter(
            Exists(epoch_end),
            Q(block__timestamp__gte=now - timedelta(days=RETENTION_DAYS)) | Q(block__timestamp__isnull=True),
        )
        .exists()
    )
