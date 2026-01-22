from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, ConnectionError

from project.core.storage.exceptions import InvalidKeyError, KeyNotFoundError
from project.core.storage.s3 import S3StorageBackend, _retry


@pytest.fixture
def client():
    return MagicMock()


@pytest.fixture
def storage(client) -> S3StorageBackend:
    return S3StorageBackend(client=client, bucket="test-bucket", prefix="test-prefix")


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("", "my-key"),
        ("/", "my-key"),
        ("/test-prefix", "test-prefix/my-key"),
        ("/test-prefix/", "test-prefix/my-key"),
        ("test/prefix", "test/prefix/my-key"),
    ],
)
def test_resolve_key(client, prefix, expected):
    storage = S3StorageBackend(client=client, bucket="test-bucket", prefix=prefix)
    assert storage.resolve_key("my-key") == expected


@pytest.mark.parametrize(
    "key",
    [
        "",  # empty after stripping
        "/",  # empty after stripping
        "abc/",  # ends with slash
        "abc%def",  # invalid character
        "abc\ndef",  # newline
    ],
)
def test_resolve_key_invalid(storage, key):
    with pytest.raises(InvalidKeyError):
        storage.resolve_key(key)


def test_store(storage, client):
    storage.store("my-key", b"test data")
    client.put_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/my-key", Body=b"test data")


def test_read(storage, client):
    mock_body = MagicMock()
    mock_body.read.return_value = b"test data"
    client.get_object.return_value = {"Body": mock_body}

    result = storage.read("my-key")

    assert result == b"test data"
    mock_body.close.assert_called_once()


def test_read_missing(storage, client):
    client.get_object.side_effect = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    with pytest.raises(KeyNotFoundError, match="Key not found"):
        storage.read("nonexistent")


def test_delete(storage, client):
    storage.delete("my-key")
    client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/my-key")


def test_exists(storage, client):
    client.head_object.return_value = {}
    assert storage.exists("my-key") is True


def test_exists_missing(storage, client):
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    assert storage.exists("nonexistent") is False


def test_exists_reraises_other_errors(storage, client):
    client.head_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "HeadObject")

    with pytest.raises(ClientError):
        storage.exists("my-key")


def test_append(storage, client):
    client.head_object.return_value = {}
    mock_body = MagicMock()
    mock_body.read.return_value = b"existing "
    client.get_object.return_value = {"Body": mock_body}

    storage.append("my-key", b"new data")

    client.get_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/my-key")
    client.put_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/my-key", Body=b"existing new data")


def test_append_missing(storage, client):
    client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")

    storage.append("new-key", b"new data")

    client.put_object.assert_called_once_with(Bucket="test-bucket", Key="test-prefix/new-key", Body=b"new data")


def test_retry_success():
    func = MagicMock(return_value={"result": "ok"})
    result = _retry(func, max_attempts=3)

    assert result == {"result": "ok"}
    assert func.call_count == 1


def test_retry_on_connection_error():
    func = MagicMock(side_effect=[ConnectionError(error=Exception("error")), {"result": "ok"}])
    result = _retry(func, max_attempts=3, base_delay=0.01)

    assert result == {"result": "ok"}
    assert func.call_count == 2


def test_retry_exhausted():
    func = MagicMock(side_effect=TimeoutError("timeout"))

    with pytest.raises(TimeoutError):
        _retry(func, max_attempts=3, base_delay=0.01)

    assert func.call_count == 3


def test_retry_non_retryable_error():
    func = MagicMock(side_effect=ValueError("not retryable"))

    with pytest.raises(ValueError):
        _retry(func, max_attempts=3)

    assert func.call_count == 1
