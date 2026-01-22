class StorageError(Exception):
    """Base class for all storage errors."""


class KeyNotFoundError(StorageError):
    """Raised when a key does not exist in storage while reading."""

    def __init__(self, key: str):
        self.key = key
        super().__init__(f"Key not found: {key}")


class InvalidKeyError(StorageError):
    """Raised when a storage key is invalid."""

    def __init__(self, key: str, reason: str):
        self.key = key
        self.reason = reason
        super().__init__(f"Invalid key '{key}': {reason}")
