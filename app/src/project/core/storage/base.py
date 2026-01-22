import re
from abc import ABC, abstractmethod

from .exceptions import InvalidKeyError


class StorageBackend(ABC):
    """
    An abstract base class for storage backends.

    A storage backend handles common operations on raw data for storing and
    retrieving data artifacts. Operations supported by the storage backend
    are atomic, and no state is maintained between operations.
    """

    @abstractmethod
    def store(self, key: str, data: bytes) -> None:
        """
        Store data at the given key.

        Args:
            key: Storage key for the data.
            data: Raw bytes to store.
        """
        pass

    @abstractmethod
    def read(self, key: str) -> bytes:
        """
        Read data from the given key.

        Args:
            key: The storage key/path to read from.

        Returns:
            Raw bytes stored at the key.

        Raises:
            KeyNotFoundError: If the key does not exist.
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete the data at the given key. If a key does not exist, this method does nothing.

        Args:
            key: Storage key/path to delete.
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if data exists at the given key.

        Args:
            key: Storage key/path to check.

        Returns:
            True if data exists at the key, otherwise False.
        """
        pass

    @abstractmethod
    def append(self, key: str, data: bytes) -> None:
        """
        Append data to the given key.

        If the key does not exist, it will be created.

        Args:
            key: Storage key/path to append to.
            data: Raw data to append.
        """
        pass

    def resolve_key(self, key: str) -> str:
        """
        Validates and resolve a key to an implementation-specific key. Subclasses can
        override to customize key validation and resolution.

        Args:
            key: The key to resolve.

        Returns:
            resolved key

        Raises:
            InvalidKeyError: If the key is invalid.
        """
        key = key.lstrip("/")

        if key.endswith("/"):
            raise InvalidKeyError(key, "key cannot end with a slash")
        if key == "":
            raise InvalidKeyError(key, "key cannot be empty")
        if not re.match(r"^[a-zA-Z0-9._/-]+$", key):  # only alphanumeric, underscore, dash, dot and slash allowed.
            raise InvalidKeyError(key, "key contains invalid characters")

        return key
