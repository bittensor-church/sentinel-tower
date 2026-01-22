import pytest

from project.core.storage.exceptions import KeyNotFoundError
from project.core.storage.memory import InMemoryStorageBackend


@pytest.fixture
def storage() -> InMemoryStorageBackend:
    return InMemoryStorageBackend()


def test_read(storage):
    storage._data = {"test-key": b"test data"}
    assert storage.read("test-key") == b"test data"


def test_read_missing(storage):
    with pytest.raises(KeyNotFoundError, match="Key not found"):
        storage.read("missing")


def test_exists(storage):
    storage._data = {"test-key": b"test data"}
    assert storage.exists("test-key") is True


def test_exists_missing(storage):
    assert storage.exists("nonexistent") is False


def test_delete(storage):
    storage._data = {"test-key": b"test data"}
    storage.delete("test-key")
    assert storage._data == {}


def test_append(storage):
    storage._data = {"test-key": b"test "}
    storage.append("test-key", b"data")
    assert storage._data == {"test-key": b"test data"}


def test_append_missing(storage):
    storage.append("test-key", b"test data")
    assert storage._data == {"test-key": b"test data"}


def test_store(storage):
    storage.store("test-key", b"test data")
    assert storage._data == {"test-key": b"test data"}


def test_store_overwrite(storage):
    storage.store("test-key", b"old data")
    storage.store("test-key", b"new data")
    assert storage._data == {"test-key": b"new data"}
