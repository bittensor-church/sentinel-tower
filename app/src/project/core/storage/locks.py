import fcntl
import hashlib
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TextIO


class Lock(ABC):
    """
    An abstract base class for implementing storage locks. Though this is designed to be used
    with storage, lock implementations are independent of storage backends.

    The idea of a lock is to mark a 'key' as locked when a lock is acquired on it and unlocked
    when the lock is released. It doesn't enforce any behavior on the actual storage
    operations.

    This makes storage locks advisory and they expect cooperation.

    Args:
        key: The key to lock.
    """

    def __init__(self, key: str) -> None:
        self._key = key
        self._acquired = False

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    @abstractmethod
    def _acquire(self, timeout: float) -> None:
        pass

    @abstractmethod
    def _release(self) -> None:
        pass

    def acquire(self, timeout: float = 10.0) -> None:
        """
        Acquire the lock.
        Args:
            timeout: Timeout in seconds. Defaults to 10 seconds.

        Raises:
            TimeoutError: If timeout is exceeded.
            RuntimeError: If a lock is already acquired.

        """
        if self._acquired:
            raise RuntimeError("Lock already acquired.")
        self._acquire(timeout)
        self._acquired = True

    def release(self) -> None:
        """
        Release the lock.
        """

        if not self._acquired:
            return
        self._release()
        self._acquired = False


class FlockLock(Lock):
    """File-based locking using fcntl.flock().

    This implementation uses a fixed pool of files. Lock files are stored in a temporary directory
    on the system. Use this lock when you need locking across processes running on the same host.
    """

    _MAX_FILES = 1024

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self._file: TextIO | None = None

    @property
    def _lock_path(self) -> Path:
        key_hash = int(hashlib.md5(self._key.encode()).hexdigest(), 16)  # noqa: S324
        file_number = key_hash % self._MAX_FILES

        _locks_dir = Path(tempfile.gettempdir()) / ".sentinel-storage-locks"
        _locks_dir.mkdir(parents=True, exist_ok=True)

        return _locks_dir / f"{file_number}.lock"

    def _acquire(self, timeout: float) -> None:
        self._file = self._lock_path.open("w")

        poll_interval = 0.1
        deadline = time.perf_counter() + timeout

        while True:
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.perf_counter() >= deadline:
                    self._file.close()
                    self._file = None
                    raise TimeoutError(f"Could not acquire lock for '{self._key}' within {timeout}s")

                time.sleep(poll_interval)

    def _release(self) -> None:
        if self._file is None:
            raise RuntimeError("Lock not acquired.")  # this should never happen, but in case we'll see the error

        fcntl.flock(self._file, fcntl.LOCK_UN)
        self._file.close()
        self._file = None


class FakeLock(Lock):
    """
    A fake lock implementation that does nothing.
    """

    def _acquire(self, timeout: float) -> None:
        pass

    def _release(self) -> None:
        pass
