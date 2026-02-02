from datetime import UTC, datetime

import structlog
from abstract_block_dumper.v1.decorators import block_task
from django.conf import settings
from sentinel.v1.services.sentinel import sentinel_service

import apps.metagraph.utils as metagraph_utils
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.sync_service import MetagraphSyncService
from apps.metagraph.tasks import fast_apy_sync
from project.core.utils import get_provider_for_block

logger = structlog.get_logger()


def _get_epoch_position(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch (start, inside, end)."""
    epoch = metagraph_utils.get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = metagraph_utils.get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


@block_task(
    condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
    args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
    celery_kwargs={"queue": "metagraph"},
)
def store_metagraph(block_number: int, netuid: int) -> str:
    """
    Store the metagraph for the given netuid at the specified block number.

    Fetches metagraph data from the blockchain, stores it as a JSONL artifact,
    and syncs it to Django models.
    """
    started_at = datetime.now(UTC)

    with get_provider_for_block(block_number) as provider:
        service = sentinel_service(provider)
        subnet = service.ingest_subnet(netuid, block_number, lite=settings.METAGRAPH_LITE)
        metagraph = subnet.metagraph

    finished_at = datetime.now(UTC)

    if not metagraph:
        logger.info(
            "No metagraph data found for block and netuid",
            block_number=block_number,
            netuid=netuid,
        )
        return ""
    # Store artifact to JSONL
    artifact_path = MetagraphService.store_metagraph_artifact(metagraph)

    # Sync to Django models
    data = metagraph.model_dump()

    # Add dump metadata if not present
    if "dump" not in data or not data["dump"]:
        data["dump"] = {}

    data["dump"].update(
        {
            "netuid": netuid,
            "epoch_position": _get_epoch_position(block_number, netuid),
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
        },
    )

    sync_service = MetagraphSyncService()
    stats = sync_service.sync_metagraph(data)

    logger.info(
        "Synced metagraph to database",
        block_number=block_number,
        netuid=netuid,
        stats=stats,
    )

    return artifact_path


@block_task(
    condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
    args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
    celery_kwargs={"queue": "metagraph"},
)
def sync_apy_data(block_number: int, netuid: int) -> str:
    """
    Dispatch a fast APY sync task for the given block and netuid.

    This block task triggers on dumpable blocks and dispatches a Celery task
    to sync minimal data required for APY calculations using native bittensor SDK.
    """
    task = fast_apy_sync.delay(block_number=block_number, netuid=netuid)

    logger.info(
        "Dispatched fast APY sync task",
        block_number=block_number,
        netuid=netuid,
        task_id=task.id,
    )

    return task.id
