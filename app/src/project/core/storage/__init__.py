from functools import cache
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from fsspec.implementations.local import LocalFileSystem
from s3fs import S3FileSystem

from .base import StorageBackend
from .fsspec import FSSpecStorageBackend


def fsspec_local_backend_factory(**options: Any) -> FSSpecStorageBackend:
    """
    Create a local filesystem storage backend using fsspec.

    Options:
        base_path: Root directory for storage. This option is required.
    """
    if "base_path" not in options or not options["base_path"]:
        raise ImproperlyConfigured("'base_path' is a required option for fsspec-local backends.")

    base_path = options["base_path"]
    if base_path.rstrip("/"):
        base_path = base_path.rstrip("/")

    fs = LocalFileSystem()
    return FSSpecStorageBackend(base_path, fs=fs)


def fsspec_s3_backend_factory(**options: Any) -> FSSpecStorageBackend:
    """
    Create an S3 storage backend using fsspec/s3fs.

    Options:
        bucket: S3 bucket name. This option is required.
        base_path: Optional prefix-path within the bucket.
        aws_region: Optional AWS region name.
        aws_access_key_id: Optional AWS access key ID.
        aws_secret_access_key: Optional AWS secret access key.
    """
    if "bucket" not in options or not options["bucket"]:
        raise ImproperlyConfigured("'bucket' is a required option for fsspec-s3 backends.")

    base_path = options.get("base_path", "")
    base_path = base_path.strip("/")
    base_path = f"{options['bucket']}/{base_path}" if base_path else options["bucket"]

    fs_options: dict[str, Any] = {}
    if (region_name := options.get("aws_region")) is not None:
        fs_options["client_kwargs"] = {"region_name": region_name}
    if (key := options.get("aws_access_key_id")) is not None:
        fs_options["key"] = key
    if (secret := options.get("aws_secret_access_key")) is not None:
        fs_options["secret"] = secret

    fs = S3FileSystem(**fs_options)
    return FSSpecStorageBackend(base_path=base_path, fs=fs)


_BACKEND_FACTORIES = {
    "fsspec-local": fsspec_local_backend_factory,
    "fsspec-s3": fsspec_s3_backend_factory,
}


def _storage_backend_factory(config: dict[str, Any]) -> StorageBackend:
    """
    Create a storage backend from a configuration dict.

    Args:
        config: Dict with 'BACKEND_NAME' and optional 'OPTIONS' keys.

    Raises:
        ImproperlyConfigured: If BACKEND_NAME is missing or unsupported.
    """
    if "BACKEND_NAME" not in config:
        raise ImproperlyConfigured("'BACKEND_NAME' is a required option for storage configurations.")

    backend_type = config["BACKEND_NAME"]
    options = config.get("OPTIONS", {})

    if backend_type not in _BACKEND_FACTORIES:
        supported = ", ".join(sorted(_BACKEND_FACTORIES.keys()))
        raise ImproperlyConfigured(
            f"Storage backend '{backend_type}' is not supported. Supported backends: {supported}"
        )

    factory = _BACKEND_FACTORIES[backend_type]
    return factory(**options)


@cache
def get_storage(name: str) -> StorageBackend:
    """
    Get a storage backend by name.

    Backends are cached after first access.

    Args:
        name: Storage name as defined in SENTINEL_STORAGES.

    Raises:
        ImproperlyConfigured: If SENTINEL_STORAGES is not defined or name not found.
    """
    storages_config = getattr(settings, "SENTINEL_STORAGES", None)
    if storages_config is None:
        raise ImproperlyConfigured("'SENTINEL_STORAGES' setting is not configured.")

    if name not in storages_config:
        raise ImproperlyConfigured(f"Storage '{name}' is not configured.")

    return _storage_backend_factory(storages_config[name])


def get_local_storage() -> StorageBackend:
    return get_storage("local")


def get_s3_storage() -> StorageBackend:
    return get_storage("s3")
