"""Block model with lazy loading."""

from functools import cached_property

from sentinel.dto import HyperparametersDTO
from sentinel.providers.bittensor import BittensorProvider
from sentinel.services.extractors.hyperparam import HyperparamExtractor


class Block:
    """
    Lazy-loading block model that extracts data on-demand.

    Data is extracted only when accessed via properties, implementing
    the lazy loading pattern to avoid unnecessary computation.
    """

    def __init__(self, provider: BittensorProvider, block_number: int, netid: int) -> None:
        """
        Initialize a Block instance.

        Args:
            provider: The blockchain provider to use for data retrieval
            block_number: The blockchain block number to process
            netid: The subnet identifier to extract hyperparameters for

        """
        self.provider = provider
        self.block_number = block_number
        self.netid = netid

    def transactions(self) -> list[dict]:
        """
        Retrieve transactions for this block.

        Returns:
            List of transactions in the block

        """
        msg = "Transaction extraction not yet implemented"
        raise NotImplementedError(msg)

    def metagraph(self) -> dict:
        """
        Retrieve metagraph for this block.

        Returns:
            Metagraph data for the block

        """
        msg = "Metagraph extraction not yet implemented"
        raise NotImplementedError(msg)

    @cached_property
    def hyperparameters(self) -> HyperparametersDTO:
        """
        Lazily extract and return hyperparameters for this block.

        The extraction only happens on first access, then cached.

        Returns:
            HyperparametersDTO containing the block's hyperparameters

        """
        extractor = HyperparamExtractor(self.provider, self.block_number, self.netid)
        return extractor.extract()