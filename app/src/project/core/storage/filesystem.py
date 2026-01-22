import os
from pathlib import Path, PurePosixPath

from .base import StorageBackend
from .exceptions import InvalidKeyError, KeyNotFoundError


class FileSystemStorageBackend(StorageBackend):
    """
    Storage backend that stores files on the local filesystem.

    Args:
        base_path: The root directory for all storage operations.
    """

    def __init__(self, base_path: str | Path):
        super().__init__()
        self.base_path = Path(base_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, key: str) -> str:
        key = super().resolve_key(key)

        path = PurePosixPath(key)
        if ".." in path.parts:
            raise InvalidKeyError(key, "relative path components are not allowed")

        path = (self.base_path / key).resolve()

        # check if we are still within the storage root
        if not path.is_relative_to(self.base_path):
            raise InvalidKeyError(key, "path escapes storage root")

        return os.fspath(path)

    def _get_path(self, key: str) -> Path:
        return Path(self.resolve_key(key))

    def store(self, key: str, data: bytes) -> None:
        path = self._get_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        path = self._get_path(key)
        if not path.exists():
            raise KeyNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        if not self.exists(key):
            return
        self._get_path(key).unlink()

    def exists(self, key: str) -> bool:
        path = self._get_path(key)
        return path.exists() and path.is_file()

    def append(self, key: str, data: bytes) -> None:
        path = self._get_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as f:
            f.write(data)
