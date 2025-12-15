from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.services.metagraph import MetagraphService


@block_task(
    condition=lambda block_number, netuid: MetagraphService.is_dumpable_block(block_number, netuid),
    args=[{"netuid": netuid} for netuid in MetagraphService.netuids_to_sync()],
)
def store_metagraph(block_number: int, netuid: int) -> str:
    """
    Store the metagraph for the given netuid at the specified block number.
    """
    pass
