from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured

from project.core.storage import get_storage_backend, get_storage_writer
from project.core.storage.filesystem import FileSystemStorageBackend
from project.core.storage.s3 import S3StorageBackend
from project.core.storage.writer import StorageWriter


def test_filesystem_backend(settings, tmp_path):
    settings.SENTINEL_STORAGE_BACKEND = "filesystem"
    settings.SENTINEL_STORAGE_OPTIONS = {"base_path": str(tmp_path)}

    backend = get_storage_backend()

    assert isinstance(backend, FileSystemStorageBackend)


def test_filesystem_missing_base_path(settings):
    settings.SENTINEL_STORAGE_BACKEND = "filesystem"
    settings.SENTINEL_STORAGE_OPTIONS = {}

    with pytest.raises(ImproperlyConfigured, match="base_path"):
        get_storage_backend()


@patch("project.core.storage.boto3")
def test_s3_backend(mock_boto3, settings):
    settings.SENTINEL_STORAGE_BACKEND = "s3"
    settings.SENTINEL_STORAGE_OPTIONS = {
        "bucket": "test-bucket",
        "prefix": "test-prefix",
        "endpoint_url": "http://localhost:9000",
        "region_name": "us-east-1",
    }

    backend = get_storage_backend()

    assert isinstance(backend, S3StorageBackend)
    assert backend.bucket == "test-bucket"
    assert backend.prefix == "test-prefix"

    mock_boto3.client.assert_called_once_with("s3", endpoint_url="http://localhost:9000", region_name="us-east-1")


def test_s3_missing_bucket(settings):
    settings.SENTINEL_STORAGE_BACKEND = "s3"
    settings.SENTINEL_STORAGE_OPTIONS = {}

    with pytest.raises(ImproperlyConfigured, match="bucket"):
        get_storage_backend()


def test_unknown_backend(settings):
    settings.SENTINEL_STORAGE_BACKEND = "unknown"
    settings.SENTINEL_STORAGE_OPTIONS = {}

    with pytest.raises(ImproperlyConfigured, match="not supported"):
        get_storage_backend()


def test_get_storage_writer(settings, tmp_path):
    settings.SENTINEL_STORAGE_BACKEND = "filesystem"
    settings.SENTINEL_STORAGE_OPTIONS = {"base_path": str(tmp_path)}

    backend = get_storage_backend()
    writer = get_storage_writer("test-key", backend)

    assert isinstance(writer, StorageWriter)
