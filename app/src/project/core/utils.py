import os

import structlog
from sentinel.v1.providers.base import BlockchainProvider
from sentinel.v1.providers.bittensor import bittensor_provider

logger = structlog.get_logger()


def get_provider_for_block(block_number: int, force_archive: bool = False) -> BlockchainProvider:
    """
    Get the appropriate provider for a block.

    Uses archive node if force_archive is True (e.g., in backfill mode).
    Otherwise returns a regular provider — callers should handle fallback
    to archive if the block is unavailable (see get_archive_provider).
    """
    archive_network = os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")

    # Check if we should force archive mode (e.g., SENTINEL_MODE=backfill)
    if not force_archive:
        force_archive = os.getenv("SENTINEL_MODE") == "backfill"

    if force_archive:
        logger.info(
            "Using archive node (forced mode)",
            block_number=block_number,
        )
        return bittensor_provider(archive_network)

    return bittensor_provider()


def get_archive_provider() -> BlockchainProvider:
    """Get a provider connected to the archive node."""
    archive_network = os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")
    return bittensor_provider(archive_network)
