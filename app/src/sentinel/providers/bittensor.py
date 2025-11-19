"""Bittensor blockchain provider."""

import logging
import os

from turbobt.block import Block
from turbobt.subnet import SubnetHyperparams

from sentinel.providers.turbobt import BittensorClient

logger = logging.getLogger(__name__)


class BittensorProvider:
    """Provider for interacting with the Bittensor blockchain."""

    def __init__(self, client: BittensorClient) -> None:
        """
        Initialize the BittensorProvider with a Bittensor client.

        Args:
            client: The Bittensor client to use for blockchain interactions

        """
        self.client = client

    def get_subnet_hyperparams(self, block_hash: str, netid: int) -> SubnetHyperparams | None:
        """
        Retrieve a block from the Bittensor blockchain.

        Args:
            block_hash: The block hash to retrieve
            netid: The subnet identifier
        Returns:
            netid hyperparameters data

        """
        return self.client.get_subnet_hyperparams(block_hash=block_hash, subnet=netid)

    def get_hash_by_block_number(self, block_number: int) -> str | None:
        """
        Retrieve the block hash for a given block number.

        Args:
            block_number: The block number to retrieve the hash for

        Returns:
            The block hash as a string, or None if not found

        """
        return self.client.get_hash_by_block_number(block_number)

    def get_current_block(self) -> Block:
        """
        Retrieve the current block from the Bittensor blockchain.

        Returns:
            Current Block instance

        """
        return self.client.current_block()


def bittensor_provider(network_uri: str | None = None) -> BittensorProvider:
    """
    Factory function to create a BittensorProvider instance.

    Args:
        network_uri: The Bittensor network URI. If not provided, reads from
                     BITTENSOR_NETWORK environment variable.

    Returns:
        BittensorProvider instance

    """
    uri = network_uri or os.getenv("BITTENSOR_NETWORK", "wss://entrypoint-finney.opentensor.ai:443")
    instance = BittensorClient(uri)
    return BittensorProvider(instance)
