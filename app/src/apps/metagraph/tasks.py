import os
import time
from datetime import UTC, datetime

import bittensor as bt
import structlog
from bittensor.core.metagraph import Metagraph
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.db import connection

from apps.metagraph.services.apy_sync_service import APYSyncService
from apps.metagraph.services.apy_sync_service import DumpMetadata as APYDumpMetadata
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

logger = structlog.get_logger()

# Connection retry settings
SUBTENSOR_CONNECTION_RETRIES = 3
SUBTENSOR_CONNECTION_BACKOFF = 5  # seconds


class SubtensorConnectionError(Exception):
    """Raised when Subtensor connection fails after all retry attempts."""

    def __init__(self, network: str, attempts: int, original_error: Exception) -> None:
        self.network = network
        self.attempts = attempts
        self.original_error = original_error
        # Consistent message format for Sentry grouping
        super().__init__(f"Subtensor connection failed after {attempts} attempts")

    def __repr__(self) -> str:
        return (
            f"SubtensorConnectionError(network={self.network!r}, "
            f"attempts={self.attempts}, original_error={self.original_error!r})"
        )


class TaskTimeLimitError(Exception):
    """Raised when a task exceeds its time limit."""

    def __init__(self, task_name: str, time_limit: int, processed: int, total: int) -> None:
        self.task_name = task_name
        self.time_limit = time_limit
        self.processed = processed
        self.total = total
        # Consistent message format for Sentry grouping
        super().__init__(f"Task {task_name} exceeded time limit ({time_limit}s)")

    def __repr__(self) -> str:
        return (
            f"TaskTimeLimitError(task_name={self.task_name!r}, time_limit={self.time_limit}, "
            f"processed={self.processed}, total={self.total})"
        )


def _create_subtensor_with_retry(network: str, max_retries: int = SUBTENSOR_CONNECTION_RETRIES) -> bt.Subtensor:
    """
    Create a Subtensor connection with retry logic for transient failures.

    Handles websocket handshake timeouts and other connection errors by retrying
    with exponential backoff before giving up.

    Raises:
        SubtensorConnectionError: When all retry attempts fail for transient errors.
        Exception: Original exception for non-transient errors.

    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            return bt.Subtensor(network=network)
        except Exception as e:
            last_error = e
            error_msg = str(e).lower()

            # Check for transient connection errors worth retrying
            is_transient = any(
                term in error_msg for term in ["timeout", "handshake", "connection", "websocket", "refused"]
            )

            if not is_transient:
                # Non-transient error, fail immediately
                logger.exception(
                    "Subtensor connection failed with non-transient error",
                    network=network,
                    attempt=attempt,
                )
                raise

            if attempt == max_retries:
                # All retries exhausted, raise clean error for Sentry
                logger.warning(
                    "Subtensor connection failed after all retries",
                    network=network,
                    attempts=attempt,
                    original_error=str(e),
                )
                raise SubtensorConnectionError(network, attempt, e) from e

            backoff = SUBTENSOR_CONNECTION_BACKOFF * attempt
            logger.warning(
                "Subtensor connection failed, retrying",
                network=network,
                attempt=attempt,
                max_retries=max_retries,
                backoff_seconds=backoff,
                error=str(e),
            )
            time.sleep(backoff)

    # Should not reach here, but satisfy type checker
    raise SubtensorConnectionError(network, max_retries, last_error)  # type: ignore[arg-type]


@shared_task(name="metagraph.refresh_apy_materialized_view")
def refresh_apy_materialized_view() -> dict:
    """
    Refresh the validator APY materialized view.

    This task should be run periodically (e.g., daily) to update the
    pre-calculated APY statistics for all validators.

    Returns:
        Dict with refresh status and timing info.

    """
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


def _get_epoch_position_str(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch (start, inside, end)."""
    epoch = get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


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
            metagraph._apply_extra_info = lambda block=None: None  # noqa: ARG005, SLF001
            metagraph.sync(block=block_number, lite=lite, subtensor=subtensor)
            return metagraph
        raise


@shared_task(
    name="metagraph.fast_apy_sync",
    autoretry_for=(Exception, TimeoutError, ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 5},
    rate_limit="1/s",  # Max 1 task per second per worker to avoid overwhelming archive node
    queue="metagraph",
)
def fast_apy_sync(
    block_number: int,
    netuid: int,
    network: str | None = None,
    *,
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


@shared_task(
    name="metagraph.fast_apy_sync_batch",
    autoretry_for=(Exception, TimeoutError, ConnectionError, OSError),
    dont_autoretry_for=(SoftTimeLimitExceeded, TaskTimeLimitError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=280,  # Catch before hard limit (300s) to handle gracefully
    queue="metagraph",
)
def fast_apy_sync_batch(
    blocks: list[tuple[int, int]],
    network: str | None = None,
    *,
    lite: bool = True,
) -> dict:
    """
    Fast sync APY-relevant data for a batch of blocks using a single connection.

    This task processes multiple blocks with a shared Subtensor connection,
    significantly reducing connection overhead compared to one task per block.

    Args:
        blocks: List of (block_number, netuid) tuples to process
        network: Bittensor network URI (default: BITTENSOR_ARCHIVE_NETWORK or "archive")
        lite: Use lite metagraph mode (default: True)

    Returns:
        Dict with batch processing stats

    """
    start_time = time.time()
    network = network or os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")
    processed = 0
    errors = 0
    total_snapshots = 0
    total_mechanism_metrics = 0
    results: list[dict] = []

    try:
        # Create a single subtensor connection for all blocks (with retry for transient failures)
        subtensor = _create_subtensor_with_retry(network=network)

        # Reuse sync service for caching benefits across blocks
        sync_service = APYSyncService()

        for block_number, netuid in blocks:
            block_start = time.time()
            started_at = datetime.now(UTC)

            try:
                # Fetch metagraph
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
                    results.append(
                        {
                            "status": "no_data",
                            "block_number": block_number,
                            "netuid": netuid,
                        },
                    )
                    continue

                # Sync using APY-optimized service
                t2 = time.time()
                dump_metadata = APYDumpMetadata(
                    netuid=netuid,
                    epoch_position=_get_epoch_position_str(block_number, netuid),
                    started_at=started_at,
                    finished_at=finished_at,
                )
                stats = sync_service.sync_metagraph(
                    metagraph=metagraph,
                    block_number=block_number,
                    block_timestamp=None,  # Skip for speed
                    dump_metadata=dump_metadata,
                )
                sync_time = time.time() - t2

                block_time = time.time() - block_start
                processed += 1
                total_snapshots += stats["snapshots"]
                total_mechanism_metrics += stats["mechanism_metrics"]

                logger.info(
                    "Batch APY: processed block",
                    block_number=block_number,
                    netuid=netuid,
                    fetch_time=round(fetch_time, 2),
                    sync_time=round(sync_time, 2),
                    block_time=round(block_time, 2),
                    snapshots=stats["snapshots"],
                )

                results.append(
                    {
                        "status": "success",
                        "block_number": block_number,
                        "netuid": netuid,
                        "fetch_time": round(fetch_time, 2),
                        "sync_time": round(sync_time, 2),
                        **stats,
                    },
                )

            except Exception as e:
                errors += 1
                logger.exception(
                    "Batch APY: failed to process block",
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
                    },
                )

        total_time = time.time() - start_time
        avg_time = total_time / len(blocks) if blocks else 0

        logger.info(
            "Fast APY sync batch completed",
            total_blocks=len(blocks),
            processed=processed,
            errors=errors,
            total_time=round(total_time, 2),
            avg_time_per_block=round(avg_time, 2),
            total_snapshots=total_snapshots,
            total_mechanism_metrics=total_mechanism_metrics,
        )

        return {
            "status": "completed",
            "total_blocks": len(blocks),
            "processed": processed,
            "errors": errors,
            "total_time": round(total_time, 2),
            "avg_time_per_block": round(avg_time, 2),
            "total_snapshots": total_snapshots,
            "total_mechanism_metrics": total_mechanism_metrics,
            "results": results,
        }

    except SoftTimeLimitExceeded:
        # Wrap in custom exception for clean Sentry grouping
        logger.warning(
            "Fast APY sync batch exceeded time limit",
            blocks_count=len(blocks),
            processed=processed,
            time_limit=280,
        )
        raise TaskTimeLimitError(
            task_name="fast_apy_sync_batch",
            time_limit=280,
            processed=processed,
            total=len(blocks),
        ) from None

    except Exception as e:
        logger.exception(
            "Fast APY sync batch failed",
            blocks_count=len(blocks),
            error=str(e),
        )
        raise
