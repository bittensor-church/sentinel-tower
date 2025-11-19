"""Bittensor blockchain provider."""

import structlog
from asgiref.sync import async_to_sync
from turbobt import Bittensor
from turbobt.block import Block
from turbobt.subnet import SubnetHyperparams

logger = structlog.get_logger()


class BittensorClient:
    """Client for interacting with the Bittensor blockchain."""

    def __init__(self, uri: str):
        self._uri = uri

    def _get_client(self):
        return Bittensor(self._uri)

    @async_to_sync
    async def current_block(self) -> Block:
        """
        Finds the current block of the blockchain.
        """
        async with self._get_client() as client:
            return await client.head.get()

    @async_to_sync
    async def get_subnet_hyperparams(self, subnet: int, block_hash: str) -> SubnetHyperparams | None:
        """
        Finds the hyperparams of given subnet at given block.
        """
        try:
            async with self._get_client() as client:
                return await client.subnet(subnet).get_hyperparameters(block_hash)
        except Exception as e:
            logger.exception(f"Failed to fetch subnet hyperparams: {e}")
        return None

    @async_to_sync
    async def get_hash_by_block_number(self, block_number: int) -> str | None:
        """
        Retrieves the block hash for a given block number.
        """
        async with self._get_client() as client:
            return await client.subtensor.chain.getBlockHash(block_number)