import boto3
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .base import StorageBackend
from .filesystem import FileSystemStorageBackend
from .locks import FlockLock
from .s3 import S3StorageBackend
from .writer import StorageWriter


def get_storage_backend() -> StorageBackend:
    """Create a storage backend configured via SENTINEL_STORAGE_* settings.

    Returns:
        A storage backend instance.

    Raises:
        django.core.exceptions.ImproperlyConfigured: If a backend type is not supported or
            required configuration options are missing.
    """
    backend: str = settings.SENTINEL_STORAGE_BACKEND
    options: dict = settings.SENTINEL_STORAGE_OPTIONS

    if backend == "filesystem":
        if "base_path" not in options:
            raise ImproperlyConfigured("'FileSystemStorageBackend' requires 'base_path' option to be set.")

        return FileSystemStorageBackend(options["base_path"])

    elif backend == "s3":
        if "bucket" not in options:
            raise ImproperlyConfigured("'S3StorageBackend' requires 'bucket' option to be set.")

        client_kwargs = {}
        for name in ("endpoint_url", "region_name", "aws_access_key_id", "aws_secret_access_key"):
            if name in options:
                client_kwargs[name] = options[name]

        client = boto3.client("s3", **client_kwargs)

        return S3StorageBackend(client=client, bucket=options["bucket"], prefix=options.get("prefix", ""))

    else:
        raise ImproperlyConfigured(f"Storage backend '{backend}' is not supported.")


def get_storage_writer(key: str, storage: StorageBackend) -> StorageWriter:
    """
    Create a StorageWriter instance for a given key and storage backend.
    Args:
        key: The storage key to use for writing data.
        storage: The storage backend to use for writing data.

    Returns:
        StorageWriter: A new StorageWriter instance.
    """
    return StorageWriter(key=key, storage=storage, lock_factory=FlockLock)  # we only have flock locks for now
