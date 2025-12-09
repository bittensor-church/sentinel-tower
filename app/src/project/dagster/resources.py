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

    def read_file(self, relative_path: str) -> list[dict[str, Any]]:
        """
        Read all JSON objects from a JSONL file.

        Args:
            relative_path: Path relative to base_path (e.g., "data/bittensor/hyperparams-extrinsics.jsonl")

        Returns:
            List of parsed JSON objects

        """
        file_path = Path(self.base_path) / relative_path
        if not file_path.exists():
            return []

        records = []
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def read_hyperparams(self) -> list[dict[str, Any]]:
        """Read all hyperparameter extrinsics."""
        return self.read_file("data/bittensor/hyperparams-extrinsics.jsonl")

    def read_set_weights(self) -> list[dict[str, Any]]:
        """Read all set-weights extrinsics."""
        return self.read_file("data/bittensor/set-weights-extrinsics.jsonl")
