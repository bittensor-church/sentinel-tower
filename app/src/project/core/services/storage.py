import json
from typing import Any

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


class JsonLinesStorage:
    """
    JSONL storage service using Django's default storage backend.

    Supports appending JSON objects as lines to files, with configurable
    path templates.

    Works with any Django storage backend:
    - Local filesystem (default)
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

    def append(self, data: Any, **path_params: Any) -> str:
        """
        Append a JSON object as a new line to the file.

        Args:
            data: The data to append (will be JSON serialized as a single line)
            **path_params: Values to substitute in the path template

        Returns:
            The path where the data was appended
        """
        file_path = self._resolve_path(**path_params)
        json_line = json.dumps(data, default=str) + "\n"

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
