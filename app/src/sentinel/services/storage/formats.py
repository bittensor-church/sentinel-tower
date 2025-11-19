"""Format strategy implementations for data serialization."""

import json
from typing import Any


class JsonFormatStrategy:
    """Formats data as JSON."""

    def serialize(self, data: dict[str, Any]) -> bytes:
        """
        Serialize data to JSON format.

        Args:
            data: Dictionary to serialize

        Returns:
            JSON bytes

        """
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def get_file_extension(self) -> str:
        """Return file extension for JSON format."""
        return ".json"
