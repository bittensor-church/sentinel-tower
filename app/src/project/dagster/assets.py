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
    records = jsonl_reader.read_hyperparams()
    dg.get_dagster_logger().info(f"Loaded {len(records)} hyperparameter extrinsics")
    return records


@dg.asset(
    group_name="blockchain_raw",
    description="List of netuids with set-weights data available",
)
def available_netuids(jsonl_reader: JsonLinesReader) -> list[int]:
    """
    Get list of netuids that have set-weights extrinsics data.
    """
    netuids = jsonl_reader.list_netuids()
    dg.get_dagster_logger().info(f"Found {len(netuids)} netuids with set-weights data: {netuids}")
    return netuids


@dg.asset(
    group_name="blockchain_raw",
    deps=[available_netuids],
    description="Raw set-weights extrinsics from all netuids",
)
def set_weights_extrinsics(
    jsonl_reader: JsonLinesReader,
    available_netuids: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """
    Load raw set-weights extrinsics from JSONL storage for all netuids.

    This asset reads set-weights-extrinsics.jsonl files for each netuid
    produced by the block ingestion pipeline.

    Returns:
        Dictionary mapping netuid to list of extrinsic records
    """
    all_weights: dict[int, list[dict[str, Any]]] = {}
    total_count = 0

    for netuid in available_netuids:
        records = jsonl_reader.read_set_weights(netuid)
        if records:
            all_weights[netuid] = records
            total_count += len(records)
            dg.get_dagster_logger().info(f"Loaded {len(records)} set-weights extrinsics for netuid {netuid}")

    dg.get_dagster_logger().info(
        f"Loaded {total_count} total set-weights extrinsics across {len(all_weights)} netuids"
    )
    return all_weights


def create_netuid_set_weights_asset(netuid: int) -> dg.AssetsDefinition:
    """
    Factory function to create a set-weights asset for a specific netuid.

    Use this to create individual assets per netuid for more granular
    pipeline control.
    """

    @dg.asset(
        name=f"set_weights_netuid_{netuid}",
        group_name="blockchain_raw",
        description=f"Set-weights extrinsics for netuid {netuid}",
    )
    def _set_weights_for_netuid(jsonl_reader: JsonLinesReader) -> list[dict[str, Any]]:
        records = jsonl_reader.read_set_weights(netuid)
        dg.get_dagster_logger().info(f"Loaded {len(records)} set-weights extrinsics for netuid {netuid}")
        return records

    return _set_weights_for_netuid


# Pre-defined assets for known netuids (can be extended as needed)
KNOWN_NETUIDS = [27, 30, 33, 52, 56, 67, 75, 77, 91, 116]

netuid_assets = [create_netuid_set_weights_asset(netuid) for netuid in KNOWN_NETUIDS]
