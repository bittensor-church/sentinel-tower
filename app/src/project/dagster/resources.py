"""Dagster resources for blockchain data processing."""
import json
from pathlib import Path
from typing import Any

from dagster import ConfigurableResource

SET_WEIGHTS_DIR = "data/bittensor/set-weights-extrinsics"


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

    def read_set_weights(self) -> tuple[list[dict[str, Any]], int]:
        """Read set-weights extrinsics from all partitioned files."""
        return self.read_partitioned_dir(SET_WEIGHTS_DIR)

    def get_hyperparams_line_count(self) -> int:
        """Get total line count of hyperparams file."""
        return self.count_lines("data/bittensor/hyperparams-extrinsics.jsonl")

    def get_set_weights_line_count(self) -> int:
        """Get total line count across all partitioned set-weights files."""
        return self.count_partitioned_lines(SET_WEIGHTS_DIR)

    def list_partitioned_files(self, relative_dir: str) -> list[str]:
        """List all JSONL files in a partitioned directory, sorted by name (date)."""
        dir_path = self._get_file_path(relative_dir)
        if not dir_path.exists():
            return []
        return sorted(f.name for f in dir_path.glob("*.jsonl"))

    def read_partitioned_dir(self, relative_dir: str) -> tuple[list[dict[str, Any]], int]:
        """
        Read all JSON objects from all JSONL files in a partitioned directory.

        Returns:
            Tuple of (list of all parsed JSON objects, total line count).

        """
        dir_path = self._get_file_path(relative_dir)
        if not dir_path.exists():
            return [], 0

        all_records = []
        total_lines = 0

        for jsonl_file in sorted(dir_path.glob("*.jsonl")):
            with jsonl_file.open(encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        all_records.append(json.loads(stripped))
                    total_lines += 1

        return all_records, total_lines

    def count_partitioned_lines(self, relative_dir: str) -> int:
        """Count total lines across all JSONL files in a partitioned directory."""
        dir_path = self._get_file_path(relative_dir)
        if not dir_path.exists():
            return 0

        total = 0
        for jsonl_file in dir_path.glob("*.jsonl"):
            with jsonl_file.open(encoding="utf-8") as f:
                for _ in f:
                    total += 1
        return total

    def read_partitioned_file(
        self, relative_dir: str, filename: str, start_line: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read a specific partitioned file from start_line onwards."""
        return self.read_file(f"{relative_dir}/{filename}", start_line)
