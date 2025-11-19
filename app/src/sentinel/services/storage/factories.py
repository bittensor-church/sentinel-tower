"""Factory functions for creating common storage service configurations."""

from pathlib import Path

from .backends import LocalBackendStrategy, S3BackendStrategy
from .formats import JsonFormatStrategy
from .objects import HyperparamsObject
from .service import StorageService


def create_local_json_storage(base_path: str | Path) -> StorageService:
    """
    Create a storage service for local JSONL files.

    Args:
        base_path: Base directory for storage

    Returns:
        Configured StorageService

    """
    return StorageService(
        storage_object=HyperparamsObject(),
        format_strategy=JsonFormatStrategy(),
        backend_strategy=LocalBackendStrategy(base_path),
    )


def create_s3_json_storage(bucket: str, *, prefix: str = "") -> StorageService:
    """
    Create a storage service for S3 JSONL files.

    Args:
        bucket: S3 bucket name
        prefix: Optional key prefix

    Returns:
        Configured StorageService

    """
    return StorageService(
        storage_object=HyperparamsObject(),
        format_strategy=JsonFormatStrategy(),
        backend_strategy=S3BackendStrategy(bucket, prefix=prefix),
    )
