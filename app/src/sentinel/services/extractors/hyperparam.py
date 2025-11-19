"""Hyperparameter extractor."""

from sentinel.dto import HyperparametersDTO
from sentinel.providers.bittensor import BittensorProvider


class HyperparamExtractor:
    """Extracts hyperparameters from a blockchain block."""

    def __init__(self, provider: BittensorProvider, block_number: int, netid: int) -> None:
        """
        Initialize the hyperparameter extractor.

        Args:
            provider: The blockchain provider to use for data retrieval
            block_number: The block hash to extract hyperparameters from
            netid: The netid identifier to extract hyperparameters for

        """
        self.provider = provider
        self.block_number = block_number
        self.netid = netid

    def extract(self) -> HyperparametersDTO:
        """
        Extract hyperparameters from the blockchain block.

        This method should query the blockchain and extract all relevant
        hyperparameter values for the given block number.

        Returns:
            HyperparametersDTO containing all extracted hyperparameters

        """
        block_hash = self.provider.get_hash_by_block_number(self.block_number)
        if not block_hash:
            msg = f"Block hash not found for block number {self.block_number}"
            raise ValueError(msg)

        hyperparameters_json = self.provider.get_subnet_hyperparams(block_hash=block_hash, netid=self.netid)
        if hyperparameters_json is None:
            msg = f"Hyperparameters not found for block {block_hash} and netid {self.netid}"
            raise ValueError(msg)

        return HyperparametersDTO.model_validate(hyperparameters_json)
