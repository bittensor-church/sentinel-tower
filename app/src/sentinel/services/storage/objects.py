"""Storage object implementations for data preparation."""

from typing import Any

from sentinel.dto import HyperparametersDTO


class HyperparamsObject:
    """Prepares hyperparameter data for storage."""

    def prepare_data(self, block_number: int, netid: int, data: HyperparametersDTO) -> dict[str, Any]:
        """
        Prepare hyperparameter data for storage.

        Args:
            data: Hyperparameters DTO
            block_number: The block_number that is being prepared for storage
            netid: The subnet identifier

        Returns:
            Dictionary with hyperparameter data

        """
        prepared = data.model_dump(mode="json")
        prepared["block_number"] = block_number
        prepared["netid"] = netid

        return prepared
