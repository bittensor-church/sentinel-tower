"""Bound collector stalls without attempting to cancel a blocked SDK thread.

Docker restarts the whole process on exit 70, creating a fresh connection. This
module has no Django/DB dependency so the health check works during DB outages.
"""

import json
import math
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class CollectorWatchdog:
    def __init__(self, path: Path, operation_timeout: float = 120, progress_timeout: float = 600):
        if any(not math.isfinite(value) or value <= 0 for value in (operation_timeout, progress_timeout)):
            raise ValueError("Collector timeouts must be finite and positive")
        self.path = path
        self.operation_timeout = operation_timeout
        self.progress_timeout = progress_timeout
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="collector-watchdog", daemon=True)
        self._progress_at = time.monotonic()
        self._block: int | None = None
        self._operation: tuple[str, float] | None = None

    @classmethod
    def from_env(cls):
        return cls(
            Path(os.environ.get("METAGRAPH_HEALTH_FILE", "/tmp/sentinel-metagraph-health.json")),
            float(os.environ.get("METAGRAPH_OPERATION_TIMEOUT_SECONDS", "120")),
            float(os.environ.get("METAGRAPH_PROGRESS_TIMEOUT_SECONDS", "600")),
        )

    def __enter__(self):
        self._progress_at = time.monotonic()  # bounded startup grace
        self._publish()
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        self.path.unlink(missing_ok=True)

    @contextmanager
    def operation(self, name: str):
        with self._lock:
            self._operation = (name, time.monotonic() + self.operation_timeout)
        try:
            yield
        finally:
            with self._lock:
                self._operation = None

    def advance(self, block: int) -> None:
        """Only completed, advancing blocks renew health; head polls/retries do not."""
        with self._lock:
            if self._block is not None and block <= self._block:
                return
            self._block = block
            self._progress_at = time.monotonic()
        self._publish()

    def _publish(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"pid": os.getpid(), "progress_at": self._progress_at, "block": self._block}))
        temporary.replace(self.path)

    def healthy(self) -> bool:
        try:
            data = json.loads(self.path.read_text())
            pid = int(data["pid"])
            if pid <= 0:
                return False
            os.kill(pid, 0)  # existence check only; no signal is delivered
            age = time.monotonic() - float(data["progress_at"])
            return 0 <= age < self.progress_timeout
        except OSError, ValueError, TypeError, KeyError, OverflowError:
            return False

    def _watch(self) -> None:
        interval = min(1.0, self.operation_timeout / 4, self.progress_timeout / 4)
        while not self._stop.wait(interval):
            now = time.monotonic()
            with self._lock:
                operation = self._operation
                stalled = now - self._progress_at >= self.progress_timeout
                block = self._block
            expired = operation is not None and now >= operation[1]
            if stalled or expired:
                # Do not depend on logging/DB/Sentry locks held by the stalled thread.
                message = {
                    "event": "Metagraph collector watchdog expired; exiting for restart",
                    "level": "error",
                    "reason": "operation_timeout" if expired else "no_block_progress",
                    "operation": operation[0] if operation else None,
                    "last_completed_block": block,
                }
                try:
                    # Docker logging backpressure must not prevent process recovery.
                    os.set_blocking(2, False)
                    os.write(2, (json.dumps(message) + "\n").encode())
                finally:
                    os._exit(70)  # sys.exit only exits this watchdog thread


if __name__ == "__main__":
    try:
        sys.exit(0 if CollectorWatchdog.from_env().healthy() else 1)
    except ValueError:
        sys.exit(1)
