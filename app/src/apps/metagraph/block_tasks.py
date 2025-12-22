import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.services.sentinel import sentinel_service

from apps.metagraph.services.metagraph_service import MetagraphService
from project.core.utils import get_provider_for_block

logger = structlog.get_logger()


# @block_task(
#     condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
#     args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
# )
def store_metagraph(block_number: int, netuid: int) -> str:
    """
    Store the metagraph for the given netuid at the specified block number.
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
    return MetagraphService.store_metagraph_artifact(metagraph)
