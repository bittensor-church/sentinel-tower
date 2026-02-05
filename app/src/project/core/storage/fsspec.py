from posixpath import dirname, join, normpath

from fsspec.spec import AbstractFileSystem

from .base import StorageBackend
from .exceptions import InvalidKeyError, KeyNotFoundError


class FSSpecStorageBackend(StorageBackend):
    """
    Storage backend that uses fsspec for file system operations.

    This allows using any fsspec-compatible file system (local, S3, GCS, etc.)
    as a storage backend.

    Args:
        fs: An fsspec AbstractFileSystem instance.
        base_path: The root directory for storage in the file system.
    """

    def __init__(self, base_path: str, fs: AbstractFileSystem) -> None:
        super().__init__()
        self._fs = fs

        if base_path.rstrip("/"):
            base_path = base_path.rstrip("/")
        self._base_path = base_path

    def store(self, key: str, data: bytes) -> None:
        key = self.resolve_key(key)
        parent = dirname(key)
        if parent:
            self._fs.makedirs(parent, exist_ok=True)
        with self._fs.open(key, "wb") as f:
            f.write(data)

    def read(self, key: str) -> bytes:
        if not self.exists(key):
            raise KeyNotFoundError(key)

        key = self.resolve_key(key)
        with self._fs.open(key, "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        if not self.exists(key):
            return

        key = self.resolve_key(key)
        self._fs.rm(key)

    def exists(self, key: str) -> bool:
        key = self.resolve_key(key)
        return self._fs.exists(key) and self._fs.isfile(key)

    def resolve_key(self, key: str) -> str:
        key = super().resolve_key(key)

        parts = key.split("/")
        if ".." in parts or "." in parts:
            raise InvalidKeyError(key, "path contains relative path components")

        full_path = normpath(join(self._base_path, key))

        if not full_path.startswith(self._base_path + "/"):
            raise InvalidKeyError(key, "path escapes storage root")

        return full_path
