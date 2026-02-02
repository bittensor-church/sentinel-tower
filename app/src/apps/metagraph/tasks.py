"""Celery tasks for metagraph data processing."""

import os
import time
from datetime import UTC, datetime

import bittensor as bt
import structlog
from bittensor.core.metagraph import Metagraph
from celery import shared_task
from django.db import connection
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from apps.metagraph.services.apy_sync_service import APYSyncService
from apps.metagraph.services.apy_sync_service import DumpMetadata as APYDumpMetadata
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.sync_service import DumpMetadata, MetagraphSyncService

logger = structlog.get_logger()


@shared_task(name="metagraph.refresh_apy_materialized_view")
def refresh_apy_materialized_view() -> dict:
    """
    Refresh the validator APY materialized view.

    This task should be run periodically (e.g., daily) to update the
    pre-calculated APY statistics for all validators.

    Returns:
        Dict with refresh status and timing info.

    """
    import time

    start_time = time.time()

    try:
        with connection.cursor() as cursor:
            # Use CONCURRENTLY to allow reads during refresh (requires unique index)
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_validator_weekly_apy")

        duration = time.time() - start_time
        logger.info(
            "Refreshed APY materialized view",
            duration_seconds=round(duration, 2),
        )

        return {
            "status": "success",
            "duration_seconds": round(duration, 2),
        }

    except Exception as e:
        duration = time.time() - start_time
        logger.exception(
            "Failed to refresh APY materialized view",
            duration_seconds=round(duration, 2),
            error=str(e),
        )
        raise


@shared_task(name="metagraph.get_top_validators_by_apy")
def get_top_validators_by_apy(limit: int = 5) -> list[dict]:
    """
    Get the top validators by weekly APY across all subnets.

    This task queries the materialized view to get the best performing
    validators from the current week.

    Args:
        limit: Number of top validators to return per subnet.

    Returns:
        List of validator APY data grouped by subnet.

    """
    from django.db import connection

    query = """
    WITH ranked AS (
        SELECT
            netuid,
            subnet_name,
            hotkey,
            weekly_apy,
            emissions_tao,
            stake_tao,
            snapshot_count,
            ROW_NUMBER() OVER (PARTITION BY netuid ORDER BY weekly_apy DESC) AS rank
        FROM mv_validator_weekly_apy
        WHERE week_start = DATE_TRUNC('week', NOW())
          AND weekly_apy > 0
    )
    SELECT
        netuid,
        subnet_name,
        hotkey,
        weekly_apy,
        emissions_tao,
        stake_tao,
        snapshot_count,
        rank
    FROM ranked
    WHERE rank <= %s
    ORDER BY netuid, rank
    """

    with connection.cursor() as cursor:
        cursor.execute(query, [limit])
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    logger.info(
        "Retrieved top validators by APY",
        total_results=len(results),
        limit_per_subnet=limit,
    )

    return results


def _get_epoch_position_str(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch (start, inside, end)."""
    from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

    epoch = get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


@shared_task(
    name="metagraph.fast_backfill_batch",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="metagraph",
)
def fast_backfill_batch(
    self,
    blocks: list[tuple[int, int]],
    network: str,
    lite: bool = True,
    store_artifact: bool = False,
) -> dict:
    """
    Fast backfill a batch of blocks using a single connection.

    This task processes multiple blocks with a shared WebSocket connection,
    significantly reducing connection overhead compared to one task per block.

    Args:
        blocks: List of (block_number, netuid) tuples to process
        network: Bittensor network URI (archive node)
        lite: Use lite metagraph mode (default: True)
        store_artifact: Whether to store JSONL artifacts (default: False)

    Returns:
        Dict with batch processing stats
    """
    start_time = time.time()
    processed = 0
    errors = 0
    total_neurons = 0
    total_weights = 0
    results: list[dict] = []

    try:
        with bittensor_provider(network) as provider:
            service = sentinel_service(provider)

            for block_number, netuid in blocks:
                block_start = time.time()
                started_at = datetime.now(UTC)

                try:
                    # Fetch metagraph (skip_timestamp for faster backfill)
                    t1 = time.time()
                    subnet = service.ingest_subnet(netuid, block_number, lite=lite, skip_timestamp=True)
                    metagraph = subnet.metagraph
                    fetch_time = time.time() - t1

                    finished_at = datetime.now(UTC)

                    if not metagraph:
                        logger.warning(
                            "No metagraph data for block",
                            block_number=block_number,
                            netuid=netuid,
                        )
                        results.append(
                            {
                                "status": "no_data",
                                "block_number": block_number,
                                "netuid": netuid,
                            }
                        )
                        continue

                    # Optionally store artifact
                    artifact_path = None
                    if store_artifact:
                        artifact_path = MetagraphService.store_metagraph_artifact(metagraph)

                    # Sync to database
                    t2 = time.time()
                    dump_metadata = DumpMetadata(
                        netuid=netuid,
                        epoch_position=_get_epoch_position_str(block_number, netuid),
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                    sync_service = MetagraphSyncService()
                    stats = sync_service.sync_from_model(metagraph, dump_metadata)
                    sync_time = time.time() - t2

                    block_time = time.time() - block_start
                    processed += 1
                    total_neurons += stats["neurons"]
                    total_weights += stats["weights"]

                    logger.info(
                        "Batch: processed block",
                        block_number=block_number,
                        netuid=netuid,
                        fetch_time=round(fetch_time, 2),
                        sync_time=round(sync_time, 2),
                        block_time=round(block_time, 2),
                    )

                    results.append(
                        {
                            "status": "success",
                            "block_number": block_number,
                            "netuid": netuid,
                            "fetch_time": round(fetch_time, 2),
                            "sync_time": round(sync_time, 2),
                            "neurons": stats["neurons"],
                            "weights": stats["weights"],
                            "artifact_path": artifact_path,
                        }
                    )

                except Exception as e:
                    errors += 1
                    logger.exception(
                        "Batch: failed to process block",
                        block_number=block_number,
                        netuid=netuid,
                        error=str(e),
                    )
                    results.append(
                        {
                            "status": "error",
                            "block_number": block_number,
                            "netuid": netuid,
                            "error": str(e),
                        }
                    )

        total_time = time.time() - start_time
        avg_time = total_time / len(blocks) if blocks else 0

        logger.info(
            "Fast backfill batch completed",
            total_blocks=len(blocks),
            processed=processed,
            errors=errors,
            total_time=round(total_time, 2),
            avg_time_per_block=round(avg_time, 2),
            total_neurons=total_neurons,
        )

        return {
            "status": "completed",
            "total_blocks": len(blocks),
            "processed": processed,
            "errors": errors,
            "total_time": round(total_time, 2),
            "avg_time_per_block": round(avg_time, 2),
            "total_neurons": total_neurons,
            "total_weights": total_weights,
            "results": results,
        }

    except Exception as e:
        logger.exception(
            "Fast backfill batch failed",
            blocks_count=len(blocks),
            error=str(e),
        )
        raise


def _get_metagraph_with_fallback(
    subtensor: bt.Subtensor,
    netuid: int,
    block_number: int,
    *,
    lite: bool = True,
) -> Metagraph | None:
    """
    Get metagraph with fallback for historical blocks.

    The bittensor SDK has a bug where it passes incorrect parameters
    for historical blocks. This function catches that error and uses
    a workaround.
    """
    try:
        return subtensor.metagraph(netuid=netuid, block=block_number, lite=lite)
    except ValueError as e:
        if "Invalid type for list data" in str(e):
            logger.warning(
                "Bittensor SDK bug encountered, using legacy metagraph sync",
                netuid=netuid,
                block_number=block_number,
            )
            # Create metagraph without syncing and patch _apply_extra_info
            metagraph = Metagraph(
                netuid=netuid,
                network=subtensor.network,
                sync=False,
                subtensor=subtensor,
            )
            metagraph._apply_extra_info = lambda block=None: None  # type: ignore[method-assign]
            metagraph.sync(block=block_number, lite=lite, subtensor=subtensor)
            return metagraph
        raise


@shared_task(
    name="metagraph.fast_apy_sync",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="metagraph",
)
def fast_apy_sync(
    self,
    block_number: int,
    netuid: int,
    network: str | None = None,
    lite: bool = True,
) -> dict:
    """
    Fast sync APY-relevant data for a single block using native bittensor SDK.

    This task syncs only the minimal data required for APY calculations:
    - Block, Subnet, Neuron, NeuronSnapshot, MechanismMetrics

    Args:
        block_number: Block number to sync
        netuid: Subnet UID
        network: Bittensor network (default: BITTENSOR_ARCHIVE_NETWORK or "archive")
        lite: Use lite metagraph mode (default: True)

    Returns:
        Dict with sync stats
    """
    start_time = time.time()
    network = network or os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")

    try:
        started_at = datetime.now(UTC)

        # Connect and fetch metagraph
        subtensor = bt.Subtensor(network=network)
        t1 = time.time()
        metagraph = _get_metagraph_with_fallback(subtensor, netuid, block_number, lite=lite)
        fetch_time = time.time() - t1

        finished_at = datetime.now(UTC)

        if metagraph is None or len(metagraph.uids) == 0:
            logger.warning(
                "No metagraph data for block",
                block_number=block_number,
                netuid=netuid,
            )
            return {
                "status": "no_data",
                "block_number": block_number,
                "netuid": netuid,
            }

        # Sync using APY-optimized service
        t2 = time.time()
        dump_metadata = APYDumpMetadata(
            netuid=netuid,
            epoch_position=_get_epoch_position_str(block_number, netuid),
            started_at=started_at,
            finished_at=finished_at,
        )
        sync_service = APYSyncService()
        stats = sync_service.sync_metagraph(
            metagraph=metagraph,
            block_number=block_number,
            block_timestamp=None,  # Skip for speed
            dump_metadata=dump_metadata,
        )
        sync_time = time.time() - t2

        total_time = time.time() - start_time

        logger.info(
            "Fast APY sync completed",
            block_number=block_number,
            netuid=netuid,
            fetch_time=round(fetch_time, 2),
            sync_time=round(sync_time, 2),
            total_time=round(total_time, 2),
            snapshots=stats["snapshots"],
            mechanism_metrics=stats["mechanism_metrics"],
        )

        return {
            "status": "success",
            "block_number": block_number,
            "netuid": netuid,
            "fetch_time": round(fetch_time, 2),
            "sync_time": round(sync_time, 2),
            "total_time": round(total_time, 2),
            **stats,
        }

    except Exception as e:
        logger.exception(
            "Fast APY sync failed",
            block_number=block_number,
            netuid=netuid,
            error=str(e),
        )
        raise
