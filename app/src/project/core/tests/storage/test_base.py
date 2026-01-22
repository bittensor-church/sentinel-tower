import pytest

from project.core.storage.base import StorageBackend
from project.core.storage.exceptions import InvalidKeyError


class ImplementedStorageBackend(StorageBackend):
    def store(self, key: str, data: bytes) -> None:
        pass

    def read(self, key: str) -> bytes:
        return b""

    def delete(self, key: str) -> None:
        pass

    def exists(self, key: str) -> bool:
        return False

    def append(self, key: str, data: bytes) -> None:
        pass


@pytest.fixture
def storage() -> ImplementedStorageBackend:
    return ImplementedStorageBackend()


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("foo", "foo"),
        ("foo/bar", "foo/bar"),
        ("foo/bar/baz.txt", "foo/bar/baz.txt"),
        ("/foo", "foo"),  # leading slash stripped
        ("//foo", "foo"),  # multiple leading slashes stripped
        ("/foo/bar", "foo/bar"),
        ("data/2024/01/file.json", "data/2024/01/file.json"),
        (".hidden", ".hidden"),  # hidden files allowed
        ("foo/.hidden/bar", "foo/.hidden/bar"),
        ("file.tar.gz", "file.tar.gz"),  # multiple dots allowed
        ("a-b_c.d", "a-b_c.d"),  # dash and underscore allowed
    ],
)
def test_valid_keys(storage, key, expected):
    assert storage.resolve_key(key) == expected


@pytest.mark.parametrize(
    "key",
    [
        "",
        "/",
        "///",
        "foo/",
        "foo/bar/",
        "foo\t$*(^*%&$^%&$bar",
    ],
)
def test_invalid_keys(storage, key):
    with pytest.raises(InvalidKeyError):
        storage.resolve_key(key)
