import time
from collections.abc import Callable
from typing import Any

import structlog
from botocore.exceptions import ClientError, ConnectionError, HTTPClientError

from .base import StorageBackend
from .exceptions import KeyNotFoundError

logger = structlog.get_logger()


# Errors that botocore's built-in retry may not handle
_RETRYABLE_EXCEPTIONS = (
    ConnectionError,
    HTTPClientError,
    TimeoutError,
    ConnectionResetError,
    BrokenPipeError,
)


def _retry(
    func: Callable[[], dict[str, Any]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 16.0,
) -> dict[str, Any]:
    last_exception: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except _RETRYABLE_EXCEPTIONS as e:
            last_exception = e
            logger.warning("S3 connection error on attempt.", attempt=attempt, max_attempts=max_attempts, error=str(e))
            if attempt < max_attempts:
                delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                time.sleep(delay)

    raise last_exception  # type: ignore[misc]


class S3StorageBackend(StorageBackend):
    """
    Storage backend that stores files in AWS S3 object storage.

    Args:
        client: A boto3 S3 client.
        bucket: The S3 bucket name.
        prefix: Optional prefix (folder path) for all keys.
    """

    def __init__(self, client: Any, bucket: str, prefix: str = ""):
        super().__init__()
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = client

    def _call_client(self, method_name: str, params: dict, *, read: bool = False) -> dict[str, Any]:
        method = getattr(self._client, method_name)

        def func() -> dict[str, Any]:
            response = method(**params)
            if read:
                body = response["Body"]
                try:
                    response["Body"] = body.read()
                finally:
                    body.close()
            return response

        return _retry(func)

    def resolve_key(self, key: str) -> str:
        key = super().resolve_key(key)
        if self.prefix:
            return f"{self.prefix}/{key}"
        return key

    def store(self, key: str, data: bytes) -> None:
        key = self.resolve_key(key)
        self._call_client("put_object", {"Bucket": self.bucket, "Key": key, "Body": data})

    def read(self, key: str) -> bytes:
        key = self.resolve_key(key)
        try:
            response = self._call_client("get_object", {"Bucket": self.bucket, "Key": key}, read=True)
            return response["Body"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise KeyNotFoundError(key) from e
            raise

    def delete(self, key: str) -> None:
        key = self.resolve_key(key)
        self._call_client("delete_object", {"Bucket": self.bucket, "Key": key})

    def exists(self, key: str) -> bool:
        key = self.resolve_key(key)
        try:
            self._call_client("head_object", {"Bucket": self.bucket, "Key": key})
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            raise

    def append(self, key: str, data: bytes) -> None:
        # this is a basic implementation. If the file sizes are too large, and
        # it impacts performance, we can use multipart upload with copying the
        # first part in-place and uploading the rest.
        if self.exists(key):
            existing_data = self.read(key)
            self.store(key, existing_data + data)
        else:
            self.store(key, data)
