"""Dagster resources for blockchain data processing."""

import json
import logging
from pathlib import Path
from typing import Any

from dagster import ConfigurableResource

logger = logging.getLogger(__name__)

EXTRINSICS_DIR = "data/bittensor/extrinsics"
METAGRAPH_DIR = "data/bittensor/metagraph"


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
        errors = 0
        with open(file_path, encoding="utf-8") as f:
            for raw_line in f:
                if current_line >= start_line:
                    stripped = raw_line.strip()
                    if stripped:
                        try:
                            records.append(json.loads(stripped))
                        except json.JSONDecodeError:
                            errors += 1
                current_line += 1

        if errors > 0:
            logger.warning("Skipped %d malformed JSON lines in %s", errors, relative_path)

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

    def read_extrinsics(self) -> tuple[list[dict[str, Any]], int]:
        """Read extrinsics from all partitioned files in the extrinsics directory."""
        return self.read_partitioned_dir(EXTRINSICS_DIR)

    def get_extrinsics_line_count(self) -> int:
        """Get total line count across all partitioned extrinsics files."""
        return self.count_partitioned_lines(EXTRINSICS_DIR)

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
        errors = 0

        for jsonl_file in sorted(dir_path.glob("*.jsonl")):
            with jsonl_file.open(encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        try:
                            all_records.append(json.loads(stripped))
                        except json.JSONDecodeError:
                            errors += 1
                    total_lines += 1

        if errors > 0:
            logger.warning("Skipped %d malformed JSON lines in %s", errors, relative_dir)

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

    def get_partitioned_total_size(self, relative_dir: str) -> int:
        """
        Get total file size in bytes across all JSONL files in a partitioned directory.

        This is much more efficient than counting lines for detecting changes in append-only files.
        """
        dir_path = self._get_file_path(relative_dir)
        if not dir_path.exists():
            return 0

        return sum(jsonl_file.stat().st_size for jsonl_file in dir_path.glob("*.jsonl"))

    def read_partitioned_file(
        self,
        relative_dir: str,
        filename: str,
        start_line: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Read a specific partitioned file from start_line onwards."""
        return self.read_file(f"{relative_dir}/{filename}", start_line)

    # Metagraph-specific methods

    def list_metagraph_netuids(self) -> list[int]:
        """List all netuid subdirectories in the metagraph directory."""
        dir_path = self._get_file_path(METAGRAPH_DIR)
        if not dir_path.exists():
            return []
        return sorted(int(subdir.name) for subdir in dir_path.iterdir() if subdir.is_dir() and subdir.name.isdigit())

    def list_metagraph_files(self, netuid: int) -> list[str]:
        """List all metagraph JSONL files for a specific netuid, sorted by block number."""
        dir_path = self._get_file_path(f"{METAGRAPH_DIR}/{netuid}")
        if not dir_path.exists():
            return []
        return sorted(f.name for f in dir_path.glob("*.jsonl"))

    def list_all_metagraph_files(self) -> list[tuple[int, str]]:
        """
        List all metagraph files across all netuids.

        Returns:
            List of (netuid, filename) tuples sorted by netuid then block number.

        """
        return [
            (netuid, filename)
            for netuid in self.list_metagraph_netuids()
            for filename in self.list_metagraph_files(netuid)
        ]

    def read_metagraph_file(self, netuid: int, filename: str) -> dict[str, Any] | None:
        """
        Read a single metagraph JSONL file.

        Args:
            netuid: The subnet ID
            filename: The filename (e.g., "12345.jsonl")

        Returns:
            The parsed metagraph data or None if file doesn't exist/is empty.

        """
        records, _ = self.read_file(f"{METAGRAPH_DIR}/{netuid}/{filename}")
        return records[0] if records else None

    def count_metagraph_files(self) -> int:
        """Count total metagraph files across all netuids."""
        return len(self.list_all_metagraph_files())

    def get_metagraph_total_size(self) -> int:
        """
        Get total file size in bytes across all metagraph JSONL files.

        This is more efficient than counting files for detecting changes.
        """
        dir_path = self._get_file_path(METAGRAPH_DIR)
        if not dir_path.exists():
            return 0

        total = 0
        for netuid_dir in dir_path.iterdir():
            if netuid_dir.is_dir() and netuid_dir.name.isdigit():
                total += sum(f.stat().st_size for f in netuid_dir.glob("*.jsonl"))
        return total

    def get_metagraph_block_numbers(self, netuid: int) -> list[int]:
        """Get all block numbers that have metagraph dumps for a netuid."""
        files = self.list_metagraph_files(netuid)
        block_numbers = []
        for f in files:
            # Filename format: {block_number}.jsonl
            try:
                block_num = int(f.replace(".jsonl", ""))
                block_numbers.append(block_num)
            except ValueError:
                continue
        return sorted(block_numbers)
