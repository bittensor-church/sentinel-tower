import pytest
from fsspec.implementations.memory import MemoryFileSystem

from project.core.storage.exceptions import InvalidKeyError, KeyNotFoundError
from project.core.storage.fsspec import FSSpecStorageBackend


@pytest.fixture
def fs() -> MemoryFileSystem:
    return MemoryFileSystem()


@pytest.fixture
def storage(fs) -> FSSpecStorageBackend:
    return FSSpecStorageBackend(base_path="/storage", fs=fs)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("abc", "/storage/abc"),
        ("/abc/def", "/storage/abc/def"),
        ("abc/.def/123/hello", "/storage/abc/.def/123/hello"),
        ("data/2024/01/file.json", "/storage/data/2024/01/file.json"),
    ],
)
def test_resolve_key(storage, key, expected):
    assert storage.resolve_key(key) == expected


@pytest.mark.parametrize("key", ("abc/../abc", "./abc", "abc/./def"))
def test_invalid_keys(storage, key):
    with pytest.raises(InvalidKeyError):
        storage.resolve_key(key)


def test_store(storage, fs):
    storage.store("my-key", b"test data")

    with fs.open("/storage/my-key", "rb") as f:
        assert f.read() == b"test data"


def test_read(storage, fs):
    with fs.open("/storage/my-key", "wb") as f:
        f.write(b"test data")

    result = storage.read("my-key")

    assert result == b"test data"


def test_read_missing(storage):
    with pytest.raises(KeyNotFoundError, match="Key not found: nonexistent"):
        storage.read("nonexistent")


def test_delete(storage, fs):
    with fs.open("/storage/my-key", "wb") as f:
        f.write(b"test data")

    storage.delete("my-key")

    assert fs.exists("/storage/my-key") is False


def test_exists(storage, fs):
    with fs.open("/storage/my-key", "wb") as f:
        f.write(b"test data")

    assert storage.exists("my-key") is True


def test_exists_missing(storage, fs):
    assert storage.exists("nonexistent") is False
