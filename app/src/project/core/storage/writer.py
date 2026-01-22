from collections.abc import Callable
from typing import Literal, Self

from .base import StorageBackend
from .locks import Lock

DEFAULT_BUFFERSIZE = 2**20  # 1 MB


class StorageWriter:
    """
    A storage writer utility that provides the following features:
    - Buffered writes to a storage backend. It is especially useful when atomic operations
      directly on the storage backend are expensive. (e.g., writing to S3)
    - Locking on the key to prevent concurrent writes.

    Examples:
        storage = FileSystemStorageBackend("/data")

        # Append mode (default): appends to an existing file
        with StorageWriter("data/bittensor/extrinsics/000.json", storage) as writer:
            for datum in data:
                    writer.write(datum)

        # Store mode: Replaces an existing file
        with StorageWriter("data.bin", storage, mode="store") as writer:
            writer.write(data)

    Args:
        key: The storage key/path for the file.
        storage: The storage backend to write to.
        lock_factory: A function that returns a Lock instance for the given key.
        buffersize: Number of bytes to buffer before auto-flushing.
        mode: "append" to append to an existing file, "store" to overwrite on the first flush.
    """

    def __init__(
        self,
        key: str,
        storage: StorageBackend,
        lock_factory: Callable[[str], Lock],
        buffersize: int = DEFAULT_BUFFERSIZE,
        mode: Literal["append", "store"] = "append",
    ):
        if mode not in {"append", "store"}:
            raise ValueError(f"Invalid mode: {mode}. Must be one of 'append' or 'store'.")

        self._key = key
        self._storage = storage
        self._buffersize = buffersize
        self._mode = mode

        self._buffer = bytearray()
        self._flushed = False

        self._lock: Lock = lock_factory(self._storage.resolve_key(self._key))

    def __enter__(self) -> Self:
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self.flush()
        finally:
            self._lock.release()

    def write(self, data: bytes) -> None:
        """
        Write bytes to the buffer.

        If the buffer reaches the configured size, it will be automatically flushed.

        Args:
            data: The bytes to write.
        """
        self._buffer.extend(data)
        if len(self._buffer) >= self._buffersize:
            self.flush()

    def flush(self) -> None:
        """
        Flush the buffer to storage.

        In the 'append' mode, buffer contents will be appended to existing data.
        In 'store' mode, the first flush overwrites the file, later flushes 'append'.
        """
        if not self._buffer:
            return

        data = bytes(self._buffer)

        if self._mode == "append" or self._flushed:
            self._storage.append(self._key, data)
        else:
            self._storage.store(self._key, data)
            self._flushed = True

        self._buffer.clear()
