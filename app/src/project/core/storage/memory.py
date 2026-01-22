from .base import StorageBackend
from .exceptions import KeyNotFoundError


class InMemoryStorageBackend(StorageBackend):
    """
    Storage backend that stores data in memory. Useful for testing and development.
    """

    def __init__(self) -> None:
        super().__init__()
        self._data: dict[str, bytes] = {}

    def store(self, key: str, data: bytes) -> None:
        key = self.resolve_key(key)
        self._data[key] = data

    def read(self, key: str) -> bytes:
        key = self.resolve_key(key)
        if key not in self._data:
            raise KeyNotFoundError(key)
        return self._data[key]

    def delete(self, key: str) -> None:
        key = self.resolve_key(key)
        self._data.pop(key, None)

    def exists(self, key: str) -> bool:
        key = self.resolve_key(key)
        return key in self._data

    def append(self, key: str, data: bytes) -> None:
        key = self.resolve_key(key)
        if key in self._data:
            self._data[key] += data
        else:
            self._data[key] = data
