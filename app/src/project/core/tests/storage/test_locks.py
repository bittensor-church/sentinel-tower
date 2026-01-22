import threading
from functools import reduce

import pytest

from project.core.storage.locks import FakeLock, FlockLock


def test_fake_lock_acquire_and_release():
    lock = FakeLock("test-key")

    lock.acquire()
    assert lock._acquired is True

    lock.release()
    assert lock._acquired is False


def test_fake_lock_double_acquire():
    lock = FakeLock("test-key")
    lock.acquire()

    with pytest.raises(RuntimeError, match="Lock already acquired"):
        lock.acquire()


def test_flock_lock_acquire_and_release():
    lock = FlockLock("test-key")

    lock.acquire()
    assert lock._acquired is True
    assert lock._file is not None

    lock.release()
    assert lock._acquired is False
    assert lock._file is None


def test_flock_lock_timeout():
    lock1 = FlockLock("timeout-test-key")
    lock2 = FlockLock("timeout-test-key")

    lock1.acquire()

    with pytest.raises(TimeoutError, match="Could not acquire lock"):
        lock2.acquire(timeout=0.1)

    lock1.release()


def test_flock_lock_concurrent_access():
    workers = 3
    lock_key = "concurrent-test-key"

    results = []
    start_barrier = threading.Barrier(workers)

    def worker(worker_id: int):
        lock = FlockLock(lock_key)
        start_barrier.wait()
        with lock:
            results.append(f"{worker_id}-start")
            reduce(lambda x, y: x + y, range(1000000), 0)
            results.append(f"{worker_id}-end")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == workers * 2
    for i in range(0, len(results), 2):
        start = results[i]
        end = results[i + 1]

        start_id, start_tag = start.split("-")
        end_id, end_tag = end.split("-")

        assert start_tag == "start"
        assert end_tag == "end"
        assert start_id == end_id, f"Interleaving detected: {results}"
