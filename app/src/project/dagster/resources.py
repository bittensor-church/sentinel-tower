"""Dagster resources for blockchain data processing."""
import json
from pathlib import Path
from typing import Any

from dagster import ConfigurableResource


class JsonLinesReader(ConfigurableResource):
    """
    Resource for reading JSONL (JSON Lines) artifact files.

    This resource provides methods to read blockchain data stored in JSONL format
    by the block_tasks ingestion pipeline.
    """

    base_path: str

    def _get_file_path(self, relative_path: str) -> Path:
        return Path(self.base_path) / relative_path

    def read_file(self, relative_path: str, start_line: int = 0) -> tuple[list[dict[str, Any]], int]:
        """
        Read JSON objects from a JSONL file, optionally starting from a specific line.

        Args:
            relative_path: Path relative to base_path
            start_line: Line number to start reading from (0-indexed)

        Returns:
            Tuple of (list of parsed JSON objects, last line number read)

        """
        file_path = self._get_file_path(relative_path)
        if not file_path.exists():
            return [], start_line

        records = []
        current_line = 0
        with open(file_path, encoding="utf-8") as f:
            for raw_line in f:
                if current_line >= start_line:
                    stripped = raw_line.strip()
                    if stripped:
                        records.append(json.loads(stripped))
                current_line += 1
        return records, current_line

    def count_lines(self, relative_path: str) -> int:
        """Count total lines in a JSONL file."""
        file_path = self._get_file_path(relative_path)
        if not file_path.exists():
            return 0

        count = 0
        with open(file_path, encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count

    def read_hyperparams(self, start_line: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Read hyperparameter extrinsics from start_line onwards."""
        return self.read_file("data/bittensor/hyperparams-extrinsics.jsonl", start_line)

    def read_set_weights(self, start_line: int = 0) -> tuple[list[dict[str, Any]], int]:
        """Read set-weights extrinsics from start_line onwards."""
        return self.read_file("data/bittensor/set-weights-extrinsics.jsonl", start_line)

    def get_hyperparams_line_count(self) -> int:
        """Get total line count of hyperparams file."""
        return self.count_lines("data/bittensor/hyperparams-extrinsics.jsonl")

    def get_set_weights_line_count(self) -> int:
        """Get total line count of set-weights file."""
        return self.count_lines("data/bittensor/set-weights-extrinsics.jsonl")
