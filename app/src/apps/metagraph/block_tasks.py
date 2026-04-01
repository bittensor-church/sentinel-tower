from datetime import UTC, datetime

import structlog
from abstract_block_dumper.v1.decorators import block_task
from django.conf import settings
from sentinel.v1.providers.bittensor import BittensorProvider
from sentinel.v1.services.sentinel import sentinel_service

import apps.metagraph.utils as metagraph_utils
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.metagraph_sync_service import DumpMetadata, MetagraphSyncService
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


def sync_metagraph_for_block(block_number: int, netuid: int, provider: BittensorProvider) -> dict | None:
    """
    Sync metagraph for the given netuid at the specified block using an existing provider.

    Fetches metagraph data from the blockchain, stores it as a JSONL artifact,
    and syncs it to Django models.

    Returns:
        Dict with sync stats and elapsed_ms, or None if no metagraph data found.

    """
    started_at = datetime.now(UTC)

    service = sentinel_service(provider)
    subnet = service.ingest_subnet(netuid, block_number, lite=settings.METAGRAPH_LITE)
    metagraph = subnet.metagraph

    finished_at = datetime.now(UTC)

    if not metagraph:
        logger.debug("No metagraph data found", block=block_number, netuid=netuid)
        return None

    MetagraphService.store_metagraph_artifact(metagraph)

    dump_metadata = DumpMetadata(
        netuid=netuid,
        epoch_position=_get_epoch_position(block_number, netuid),
        started_at=started_at,
        finished_at=finished_at,
    )

    sync_service = MetagraphSyncService()
    stats = sync_service.sync_metagraph(metagraph, dump_metadata)

    elapsed_ms = round((datetime.now(UTC) - started_at).total_seconds() * 1000)

    return {"neurons": stats["neurons"], "weights": stats["weights"], "bonds": stats["bonds"], "elapsed_ms": elapsed_ms}


@block_task(
    condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
    args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
    celery_kwargs={"queue": "metagraph"},
)
def store_metagraph(block_number: int, netuid: int) -> dict | None:
    """
    Store the metagraph for the given netuid at the specified block number.

    Fetches metagraph data from the blockchain, stores it as a JSONL artifact,
    and syncs it to Django models.
    """
    provider_ctx = get_provider_for_block(block_number)

    with provider_ctx as provider:
        return sync_metagraph_for_block(block_number, netuid, provider)


# @block_task(
#     condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
#     args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
#     celery_kwargs={"queue": "metagraph"},
# )
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
