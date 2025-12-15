"""Dagster assets for blockchain data processing."""

from typing import Any

import dagster as dg

from project.dagster.resources import JsonLinesReader


@dg.asset(
    group_name="blockchain_raw",
    description="Raw hyperparameter extrinsics from the Bittensor blockchain",
)
def hyperparams_extrinsics(jsonl_reader: JsonLinesReader) -> list[dict[str, Any]]:
    """
    Load raw hyperparameter extrinsics from JSONL storage.

    This asset reads the hyperparams-extrinsics.jsonl file produced by the
    block ingestion pipeline.
    """
    records, _ = jsonl_reader.read_hyperparams()
    dg.get_dagster_logger().info(f"Loaded {len(records)} hyperparameter extrinsics")
    return records
