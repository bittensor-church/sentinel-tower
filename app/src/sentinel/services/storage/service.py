"""Main storage service for orchestrating data preparation, formatting, and persistence."""

from sentinel.dto import HyperparametersDTO

from .protocols import BackendStrategy, FormatStrategy, StorageObject


class StorageService:
    """Orchestrates data preparation, formatting, and persistence."""

    def __init__(
        self,
        storage_object: StorageObject,
        format_strategy: FormatStrategy,
        backend_strategy: BackendStrategy,
    ) -> None:
        """
        Initialize storage service.

        Args:
            storage_object: Object that prepares data
            format_strategy: Strategy for data serialization
            backend_strategy: Strategy for data persistence

        """
        self.storage_object = storage_object
        self.format_strategy = format_strategy
        self.backend_strategy = backend_strategy

    def store(self, block_number: int, netid: int, data: HyperparametersDTO, path: str) -> str:
        """
        Store data using the configured strategies.

        Args:
            block_number: The block number being stored
            netid: The subnet identifier
            data: Data to store
            path: Destination path (without extension)

        Returns:
            Full path/URI where data was stored

        Raises:
            ValueError: If data preparation fails

        """
        # Step 1: Prepare data
        prepared_data = self.storage_object.prepare_data(block_number, netid, data)
        if not prepared_data:
            msg = "Data preparation returned empty result"
            raise ValueError(msg)

        # Step 2: Serialize to format
        serialized = self.format_strategy.serialize(prepared_data)

        # Step 3: Add extension to path
        full_path = path + self.format_strategy.get_file_extension()

        # Step 4: Write to backend
        return self.backend_strategy.write(serialized, full_path)
