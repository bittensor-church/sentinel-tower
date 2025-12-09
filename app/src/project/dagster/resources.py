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

    def read_set_weights(self, netuid: int) -> list[dict[str, Any]]:
        """
        Read set-weights extrinsics for a specific netuid.

        Args:
            netuid: The network UID to read data for

        Returns:
            List of set-weights extrinsic records
        """
        return self.read_file(f"data/bittensor/netuid/{netuid}/set-weights-extrinsics.jsonl")

    def list_netuids(self) -> list[int]:
        """
        List all netuids that have set-weights data.

        Returns:
            List of netuid integers
        """
        netuid_dir = Path(self.base_path) / "data" / "bittensor" / "netuid"
        if not netuid_dir.exists():
            return []

        netuids = []
        for subdir in netuid_dir.iterdir():
            if subdir.is_dir() and subdir.name.isdigit():
                weights_file = subdir / "set-weights-extrinsics.jsonl"
                if weights_file.exists():
                    netuids.append(int(subdir.name))
        return sorted(netuids)
