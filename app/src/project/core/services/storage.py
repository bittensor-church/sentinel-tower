import fcntl
import json
import os
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


class JsonLinesStorage:
    """
    JSONL storage service using Django's default storage backend.

    Supports appending JSON objects as lines to files, with configurable
    path templates.

    Works with any Django storage backend:
    - Local filesystem (default) - uses file locking for concurrency safety
    - S3 (when django-storages with S3 backend is configured)
    - Any other configured storage backend

    Example:
        storage = JsonLinesStorage("data/bittensor/netuids/{netuid}/hyperparams.jsonl")
        storage.append({"block": 123, "value": 42}, netuid=1)
        # Writes to: data/bittensor/netuids/1/hyperparams.jsonl
    """

    def __init__(self, path_template: str):
        """
        Initialize the storage service.

        Args:
            path_template: Path template with optional placeholders.
                           e.g., "data/bittensor/netuids/{netuid}/hyperparams.jsonl"
        """
        self.path_template = path_template

    def _resolve_path(self, **kwargs: Any) -> str:
        """Resolve the path template with provided values."""
        return self.path_template.format(**kwargs)

    def _get_absolute_path(self, relative_path: str) -> Path:
        """Get absolute filesystem path for local storage."""
        media_root = getattr(settings, "MEDIA_ROOT", "")
        return Path(media_root) / relative_path

    def _is_local_storage(self) -> bool:
        """Check if using local filesystem storage."""
        storage_class = default_storage.__class__.__name__
        return storage_class in ("FileSystemStorage", "OverwriteStorage")

    def append(self, data: Any, **path_params: Any) -> str:
        """
        Append a JSON object as a new line to the file.

        Thread-safe for local filesystem storage using file locking.

        Args:
            data: The data to append (will be JSON serialized as a single line)
            **path_params: Values to substitute in the path template

        Returns:
            The path where the data was appended
        """
        file_path = self._resolve_path(**path_params)
        json_line = json.dumps(data, default=str) + "\n"

        if self._is_local_storage():
            return self._append_local(file_path, json_line)
        return self._append_storage(file_path, json_line)

    def _append_local(self, file_path: str, json_line: str) -> str:
        """
        Append to local file with locking for concurrency safety.

        Uses fcntl.flock() for exclusive access during write.
        """
        abs_path = self._get_absolute_path(file_path)

        # Ensure parent directory exists
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # Open in append mode with exclusive lock
        with abs_path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(json_line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return file_path

    def _append_storage(self, file_path: str, json_line: str) -> str:
        """
        Append using Django storage backend (for S3, etc.).

        Note: This is not fully atomic for remote storage backends.
        For high-concurrency scenarios with S3, consider using
        a different approach (e.g., one file per record).
        """
        if default_storage.exists(file_path):
            with default_storage.open(file_path, "r") as f:
                existing_content = f.read()
            content = existing_content + json_line
            default_storage.delete(file_path)
        else:
            content = json_line

        default_storage.save(file_path, ContentFile(content.encode("utf-8")))
        return file_path

    def read_all(self, **path_params: Any) -> list[Any]:
        """
        Read all JSON objects from the file.

        Args:
            **path_params: Values to substitute in the path template

        Returns:
            List of parsed JSON objects
        """
        file_path = self._resolve_path(**path_params)

        if not default_storage.exists(file_path):
            return []

        with default_storage.open(file_path, "r") as f:
            return [json.loads(line) for line in f if line.strip()]

    def overwrite(self, data_list: list[Any], **path_params: Any) -> str:
        """
        Overwrite the file with a list of JSON objects.

        Args:
            data_list: List of objects to write
            **path_params: Values to substitute in the path template

        Returns:
            The path where the file was written
        """
        file_path = self._resolve_path(**path_params)
        content = "\n".join(json.dumps(item, default=str) for item in data_list)
        if content:
            content += "\n"

        if default_storage.exists(file_path):
            default_storage.delete(file_path)

        default_storage.save(file_path, ContentFile(content.encode("utf-8")))
        return file_path

    def exists(self, **path_params: Any) -> bool:
        """Check if the file exists."""
        return default_storage.exists(self._resolve_path(**path_params))

    def delete(self, **path_params: Any) -> bool:
        """
        Delete the file.

        Returns:
            True if deleted, False if file didn't exist
        """
        file_path = self._resolve_path(**path_params)

        if not default_storage.exists(file_path):
            return False

        default_storage.delete(file_path)
        return True

    def get_url(self, **path_params: Any) -> str | None:
        """
        Get the URL for accessing the file.

        For S3, this returns the S3 URL.
        For local storage, this returns the media URL path.
        """
        file_path = self._resolve_path(**path_params)

        if not default_storage.exists(file_path):
            return None

        return default_storage.url(file_path)
