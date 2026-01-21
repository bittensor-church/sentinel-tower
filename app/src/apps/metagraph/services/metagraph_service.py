from typing import Optional

import structlog
from django.conf import settings
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.extractors.metagraph.dto import FullSubnetSnapshot

import apps.metagraph.utils as metagraph_utils
from project.core.services import JsonLinesStorage

logger = structlog.get_logger()


class MetagraphService:
    @classmethod
    def is_dumpable_block(cls, block_number: int, netuid: int) -> bool:
        """
        Determine if the metagraph for the given netuid should be dumped at the specified block number.

        Args:
            block_number: The blockchain block number to check
            netuid: The subnet ID to check
        Returns:
            True if the metagraph should be dumped, False otherwise

        """
        epoch = metagraph_utils.get_epoch_containing_block(block_number, netuid)
        dumpable_blocks = metagraph_utils.get_dumpable_blocks(epoch)
        return block_number in dumpable_blocks

    @classmethod
    def netuids_to_sync(cls) -> list[int]:
        """
        Get a list of netuids that should be synchronized.

        Returns:
            List of netuids to sync

        """
        if settings.METAGRAPH_NETUIDS:
            return settings.METAGRAPH_NETUIDS

        return list(range(1, 129))

    @classmethod
    def store_metagraph_artifact(cls, metagraph: FullSubnetSnapshot) -> str:
        """Serialize and store the metagraph artifact in JSONL format."""
        storage = JsonLinesStorage("data/bittensor/metagraph/{netuid}/{block_number}.jsonl")

        netuid = metagraph.subnet.netuid
        block_number = metagraph.block.block_number

        logger.info(
            "Storing metagraph artifact",
            netuid=netuid,
            block_number=block_number,
        )

        return storage.append(
            metagraph.model_dump(),
            netuid=netuid,
            block_number=block_number,
        )
