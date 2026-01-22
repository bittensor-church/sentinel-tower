import pytest

from project.core.storage.exceptions import InvalidKeyError, KeyNotFoundError
from project.core.storage.filesystem import FileSystemStorageBackend


@pytest.fixture
def storage(tmp_path) -> FileSystemStorageBackend:
    return FileSystemStorageBackend(tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "",  # empty
        "/abc/",  # ends with slash
        "/%2F/abc",  # invalid characters
        "abc/../abc",  # relative path
    ],
)
def test_resolve_key_invalid_keys(storage, key):
    with pytest.raises(InvalidKeyError):
        storage.resolve_key(key)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("abc", "abc"),
        ("/abc/def", "abc/def"),
        ("abc/.def/123/hello", "abc/.def/123/hello"),
    ],
)
def test_resolve_key_valid_keys(tmp_path, storage, key, expected):
    assert storage.resolve_key(key) == f"{tmp_path}/{expected}"


def test_store_and_read(storage):
    storage.store("test-key", b"test data")
    assert storage.read("test-key") == b"test data"


def test_read_missing(storage):
    with pytest.raises(KeyNotFoundError, match="Key not found"):
        storage.read("missing")


def test_exists(storage):
    storage.store("test-key", b"test data")
    assert storage.exists("test-key") is True


def test_exists_missing(storage):
    assert storage.exists("nonexistent") is False


def test_delete(storage):
    storage.store("test-key", b"test data")
    storage.delete("test-key")
    assert storage.exists("test-key") is False


def test_append(storage):
    storage.store("test-key", b"test ")
    storage.append("test-key", b"data")
    assert storage.read("test-key") == b"test data"


def test_append_missing(storage):
    storage.append("new-key", b"test data")
    assert storage.read("new-key") == b"test data"


def test_store_overwrite(storage):
    storage.store("test-key", b"old data")
    storage.store("test-key", b"new data")
    assert storage.read("test-key") == b"new data"
