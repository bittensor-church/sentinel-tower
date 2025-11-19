"""Protocol definitions for storage strategies."""

from typing import Any, Protocol

from sentinel.dto import HyperparametersDTO


class StorageObject(Protocol):
    """Protocol for objects that prepare data for storage."""

    def prepare_data(self, block_number: int, netid: int, data: HyperparametersDTO) -> dict[str, Any]:
        """
        Prepare data for storage by converting DTO to dictionary.

        Args:
            data: The DTO to prepare
            block_number: The block number that is being stored
            netid: The subnet identifier

        Returns:
            Dictionary representation of the data

        Raises:
            ValueError: If data preparation fails

        """
        ...


class FormatStrategy(Protocol):
    """Protocol for formatting/serializing data."""

    def serialize(self, data: dict[str, Any]) -> bytes:
        """
        Serialize data to bytes in the target format.

        Args:
            data: Dictionary data to serialize

        Returns:
            Serialized bytes

        """
        ...

    def get_file_extension(self) -> str:
        """Get the file extension for this format (e.g., '.jsonl', '.parquet')."""
        ...


class BackendStrategy(Protocol):
    """Protocol for backend storage implementations."""

    def write(self, data: bytes, path: str) -> str:
        """
        Write data to the backend storage.

        Args:
            data: Serialized data bytes
            path: Destination path/key

        Returns:
            Full path/URI where data was stored

        """
        ...
