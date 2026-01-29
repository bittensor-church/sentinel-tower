from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from fsspec.implementations.local import LocalFileSystem

from project.core.storage import (
    _storages,
    fsspec_local_backend_factory,
    fsspec_s3_backend_factory,
    get_default_storage,
    get_storage,
)
from project.core.storage.fsspec import FSSpecStorageBackend


@pytest.fixture(autouse=True)
def clear_storage_cache():
    _storages.clear()
    yield
    _storages.clear()


def test_get_storage(settings, tmp_path):
    settings.SENTINEL_STORAGES = {
        "default": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path)},
        }
    }

    storage = get_storage("default")

    assert isinstance(storage, FSSpecStorageBackend)


def test_get_storage_cache(settings, tmp_path):
    settings.SENTINEL_STORAGES = {
        "default": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path)},
        }
    }

    storage1 = get_storage("default")
    storage2 = get_storage("default")

    assert storage1 is storage2


def test_get_storage_no_configured(settings):
    settings.SENTINEL_STORAGES = None

    with pytest.raises(ImproperlyConfigured, match="'SENTINEL_STORAGES' setting is not configured."):
        get_storage("default")


def test_get_storage_unknown(settings, tmp_path):
    settings.SENTINEL_STORAGES = {
        "default": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path)},
        }
    }

    with pytest.raises(ImproperlyConfigured, match="Storage 'unknown' is not configured."):
        get_storage("unknown")


def test_get_storage_multiple_backends(settings, tmp_path):
    settings.SENTINEL_STORAGES = {
        "default": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path)},
        },
        "extrinsics": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path / "extrinsics")},
        },
    }

    default_storage = get_storage("default")
    artifacts_storage = get_storage("extrinsics")

    assert default_storage is not artifacts_storage
    assert isinstance(default_storage, FSSpecStorageBackend)
    assert isinstance(artifacts_storage, FSSpecStorageBackend)


def test_get_default_storage(settings, tmp_path):
    settings.SENTINEL_STORAGES = {
        "default": {
            "BACKEND_NAME": "fsspec-local",
            "OPTIONS": {"base_path": str(tmp_path)},
        }
    }

    storage = get_default_storage()

    assert storage is get_storage("default")


def test_fsspec_local_backend_factory(tmp_path):
    result = fsspec_local_backend_factory(base_path=str(tmp_path))

    assert isinstance(result, FSSpecStorageBackend)
    assert isinstance(result._fs, LocalFileSystem)


def test_fsspec_local_backend_factory_missing_base_path():
    with pytest.raises(ImproperlyConfigured, match="'base_path' is a required option for fsspec-local backends."):
        fsspec_local_backend_factory()


@patch("project.core.storage.S3FileSystem")
def test_fsspec_s3_backend_factory(s3_file_system_mock):
    result = fsspec_s3_backend_factory(
        bucket="test-bucket",
        aws_region="region",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
    )

    assert isinstance(result, FSSpecStorageBackend)
    assert s3_file_system_mock.called
    s3_file_system_mock.assert_called_once_with(key="key", secret="secret", client_kwargs={"region_name": "region"})


def test_fsspec_s3_backend_factory_missing_bucket_name():
    with pytest.raises(ImproperlyConfigured, match="'bucket' is a required option for fsspec-s3 backends."):
        fsspec_s3_backend_factory()
