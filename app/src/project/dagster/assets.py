"""Dagster assets for blockchain data processing."""

from typing import Any

import dagster as dg

from project.dagster.resources import JsonLinesReader


@dg.asset(
    group_name="blockchain_raw",
    description="Raw extrinsics from the Bittensor blockchain",
)
def extrinsics(jsonl_reader: JsonLinesReader) -> list[dict[str, Any]]:
    """
    Load raw extrinsics from JSONL storage.

    This asset reads the partitioned extrinsics JSONL files produced by the
    block ingestion pipeline.
    """
    records, _ = jsonl_reader.read_extrinsics()
    dg.get_dagster_logger().info(f"Loaded {len(records)} extrinsics")
    return records
