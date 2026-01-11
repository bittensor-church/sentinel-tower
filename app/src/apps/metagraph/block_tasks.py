import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.services.sentinel import sentinel_service

from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.sync_service import MetagraphSyncService
from project.core.utils import get_provider_for_block

logger = structlog.get_logger()


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
    with get_provider_for_block(block_number) as provider:
        service = sentinel_service(provider)
        subnet = service.ingest_subnet(netuid, block_number)
        metagraph = subnet.metagraph

    if not metagraph:
        logger.info(
            "No metagraph data found for block and netuid",
            block_number=block_number,
            netuid=netuid,
        )
        return ""

    # Store artifact to JSONL
    artifact_path = MetagraphService.store_metagraph_artifact(metagraph)

    # TODO: Store directly from the provider to avoid double fetching
    # Sync to Django models
    data = metagraph.model_dump()
    sync_service = MetagraphSyncService()
    stats = sync_service.sync_metagraph(data)

    logger.info(
        "Synced metagraph to database",
        block_number=block_number,
        netuid=netuid,
        stats=stats,
    )

    return artifact_path
