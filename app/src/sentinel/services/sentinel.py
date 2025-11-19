"""Sentinel service for blockchain ingestion."""

from sentinel.models.block import Block
from sentinel.providers.bittensor import BittensorProvider


class SentinelService:
    """Service for ingesting and processing blockchain blocks."""

    def __init__(self, provider: BittensorProvider) -> None:
        """
        Initialize the SentinelService with a blockchain provider.

        Args:
            provider: The blockchain provider to use for data retrieval

        """
        self.provider = provider

    def ingest_block(self, block_number: int, netuid: int) -> Block:
        """
        Ingest a block for netuid and return a lazy-loaded Block instance.

        The returned Block object uses lazy loading - data extractors
        are only triggered when their corresponding properties are accessed.

        Args:
            block_number: The blockchain block number to ingest
            netuid: The subnet identifier to extract hyperparameters for

        Returns:
            Block instance with lazy-loaded properties

        """
        return Block(self.provider, block_number, netuid)


def sentinel_service(provider: BittensorProvider) -> SentinelService:
    """
    Factory function to create a SentinelService service instance.

    Returns:
        SentinelService service instance

    """
    return SentinelService(provider)
