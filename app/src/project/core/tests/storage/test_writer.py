import pytest

from project.core.storage.locks import FakeLock
from project.core.storage.memory import InMemoryStorageBackend
from project.core.storage.writer import StorageWriter


@pytest.fixture
def storage() -> InMemoryStorageBackend:
    return InMemoryStorageBackend()


@pytest.fixture
def writer(storage) -> StorageWriter:
    return StorageWriter("test-key", storage, buffersize=10, lock_factory=FakeLock)


def test_write(storage, writer):
    with writer:
        writer.write(b"test ")
        writer.write(b"test")
        assert storage._data == {}
        writer.write(b" data")

    assert storage._data == {"test-key": b"test test data"}


def test_auto_flush(storage, writer):
    with writer:
        writer.write(b"x" * 15)
        assert storage._data == {"test-key": b"x" * 15}
        writer.write(b"x" * 5)

    assert storage._data == {"test-key": b"x" * 20}


def test_manual_flush(storage, writer):
    with writer:
        writer.write(b"x" * 5)
        writer.flush()
        assert storage._data == {"test-key": b"x" * 5}
        writer.write(b"x" * 5)

    assert storage._data == {"test-key": b"x" * 10}


def test_append_mode(storage, writer):
    storage._data = {"test-key": b"existing data "}

    with writer:
        writer.write(b"new data")

    assert storage.read("test-key") == b"existing data new data"


def test_store_mode(storage):
    storage._data = {"test-key": b"existing data"}

    writer = StorageWriter("test-key", storage, mode="store", lock_factory=FakeLock)
    with writer:
        writer.write(b"new data")

    assert storage.read("test-key") == b"new data"


def test_empty_flush(storage, writer):
    with writer:
        writer.flush()

    assert storage.exists("test-key") is False


def test_invalid_mode(storage):
    with pytest.raises(ValueError, match="Invalid mode"):
        StorageWriter("test-key", storage, mode="invalid", lock_factory=FakeLock)  # type: ignore
