import os

import structlog
from sentinel.v1.providers.bittensor import BittensorProvider, bittensor_provider

logger = structlog.get_logger()

# Number of blocks behind current head after which archive node is required
ARCHIVE_THRESHOLD_BLOCKS = 300


def get_provider_for_block(block_number: int) -> BittensorProvider:
    """
    Get the appropriate provider for a block.

    Uses archive node for blocks older than ARCHIVE_THRESHOLD_BLOCKS.
    """
    archive_uri = os.getenv("BITTENSOR_ARCHIVE_NETWORK")
    if not archive_uri:
        return bittensor_provider()

    # Get current block to determine if we need archive
    with bittensor_provider() as provider:
        current_block = provider.get_current_block()

    if current_block - block_number > ARCHIVE_THRESHOLD_BLOCKS:
        logger.info(
            "Using archive node for old block",
            block_number=block_number,
            current_block=current_block,
            threshold=ARCHIVE_THRESHOLD_BLOCKS,
        )
        return bittensor_provider(archive_uri)

    return bittensor_provider()
