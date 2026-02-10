"""Fast backfill command using native bittensor SDK with archive node."""

import os
import time
from datetime import UTC, datetime

import bittensor as bt
import structlog
from bittensor.core.metagraph import Metagraph
from django.core.management.base import BaseCommand

from apps.metagraph.services.apy_sync_service import APYSyncService, DumpMetadata
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

logger = structlog.get_logger()


def _get_metagraph_with_fallback(
    subtensor: bt.Subtensor,
    netuid: int,
    block_number: int,
    lite: bool = True,
) -> Metagraph | None:
    """
    Get metagraph with fallback for historical blocks.

    The bittensor SDK has a bug where it passes incorrect parameters
    for historical blocks. This function catches that error and uses
    a workaround that patches _apply_extra_info to be a no-op.
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
            return _get_metagraph_legacy(subtensor, netuid, block_number, lite=lite)
        raise


def _get_metagraph_legacy(
    subtensor: bt.Subtensor,
    netuid: int,
    block_number: int,
    lite: bool = True,
) -> Metagraph | None:
    """
    Legacy metagraph retrieval for historical blocks.

    This bypasses the buggy _runtime_call_with_fallback in the SDK
    by patching _apply_extra_info to be a no-op during sync.
    """
    # Create metagraph without syncing
    metagraph = Metagraph(
        netuid=netuid,
        network=subtensor.network,
        sync=False,
        subtensor=subtensor,
    )

    try:
        # Patch _apply_extra_info to skip the buggy code path
        original_apply_extra_info = metagraph._apply_extra_info

        def patched_apply_extra_info(block: int) -> None:
            # Skip the buggy get_metagraph_info call for historical blocks
            logger.debug(
                "Skipping _apply_extra_info for historical block",
                block_number=block,
                netuid=netuid,
            )

        metagraph._apply_extra_info = patched_apply_extra_info  # type: ignore[method-assign]

        # Now sync - this will populate the metagraph with neuron data
        # but skip the buggy _apply_extra_info call
        metagraph.sync(block=block_number, lite=lite, subtensor=subtensor)

        # Restore the original method
        metagraph._apply_extra_info = original_apply_extra_info  # type: ignore[method-assign]

        return metagraph
    except Exception:
        logger.exception(
            "Failed to get legacy metagraph",
            netuid=netuid,
            block_number=block_number,
        )
        return None


def _get_epoch_position_str(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch (start, inside, end)."""
    epoch = get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


def _get_epoch_start_blocks_in_range(from_block: int, to_block: int, netuid: int) -> list[int]:
    """
    Get epoch start blocks in a range for a given netuid.

    Only returns the first block of each epoch (for APY calculation we only need one snapshot per epoch).
    """
    epoch_starts = set()
    current_block = from_block

    while current_block <= to_block:
        epoch = get_epoch_containing_block(current_block, netuid)
        epoch_start = epoch.start

        if from_block <= epoch_start <= to_block:
            epoch_starts.add(epoch_start)

        # Move to the next epoch
        current_block = epoch.stop + 1

    return sorted(epoch_starts)


class Command(BaseCommand):
    help = "Fast backfill historical blocks using native bittensor SDK with archive node."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--from-block",
            type=int,
            required=True,
            help="Starting block number (inclusive)",
        )
        parser.add_argument(
            "--to-block",
            type=int,
            required=True,
            help="Ending block number (inclusive)",
        )
        parser.add_argument(
            "--netuid",
            type=int,
            default=None,
            help="Subnet UID to backfill (default: all configured netuids)",
        )
        parser.add_argument(
            "--network",
            type=str,
            default=None,
            help="Bittensor network URI (default: BITTENSOR_ARCHIVE_NETWORK env var)",
        )
        parser.add_argument(
            "--lite",
            action="store_true",
            default=True,
            help="Use lite metagraph (default: True)",
        )
        parser.add_argument(
            "--step",
            type=int,
            default=1,
            help="Block step size (default: 1, process every block)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview blocks without storing",
        )
        parser.add_argument(
            "--async",
            dest="use_async",
            action="store_true",
            help="Dispatch Celery tasks for parallel processing (default: synchronous)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of tasks to dispatch per batch in async mode (default: 100)",
        )
        parser.add_argument(
            "--batch-delay",
            type=float,
            default=1.0,
            help="Delay in seconds between batches in async mode (default: 1.0)",
        )
        parser.add_argument(
            "--time-per-block",
            type=float,
            default=None,
            help="Estimated seconds per block for dry-run time calculation (e.g., 2.5)",
        )

    def handle(self, *args, **options) -> None:
        from_block = options["from_block"]
        to_block = options["to_block"]
        netuid = options["netuid"]
        network = options["network"] or os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")
        lite = options["lite"]
        step = options["step"]
        dry_run = options["dry_run"]
        use_async = options["use_async"]
        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]
        time_per_block = options["time_per_block"]

        # Validate
        if from_block > to_block:
            self.stderr.write(self.style.ERROR(f"--from-block ({from_block}) must be <= --to-block ({to_block})"))
            return

        if not network:
            self.stderr.write(
                self.style.ERROR("Network not specified. Set --network or BITTENSOR_ARCHIVE_NETWORK env var")
            )
            return

        # Get netuids to process
        if netuid is not None:
            netuids = [netuid]
        else:
            netuids = MetagraphService.netuids_to_sync()
            if not netuids:
                self.stderr.write(
                    self.style.ERROR("No netuids configured. Set --netuid or configure METAGRAPH_NETUIDS")
                )
                return

        total_blocks = (to_block - from_block) // step + 1
        self.stdout.write(f"Fast backfill: blocks {from_block} -> {to_block} (step={step}, total={total_blocks})")
        self.stdout.write(f"  Network: {network}")
        self.stdout.write(f"  Subnets: {netuids}")
        self.stdout.write(f"  Lite: {lite}")
        self.stdout.write(f"  Async: {use_async}")
        if use_async:
            self.stdout.write(f"  Batch size: {batch_size}, Batch delay: {batch_delay}s")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN - No data will be stored ===\n"))

            # Calculate blocks per subnet
            subnet_blocks: dict[int, list[int]] = {}
            total_tasks = 0
            for uid in netuids:
                dumpable_blocks = _get_epoch_start_blocks_in_range(from_block, to_block, uid)
                blocks_to_process = dumpable_blocks[::step]
                subnet_blocks[uid] = blocks_to_process
                total_tasks += len(blocks_to_process)

            # Display summary
            self.stdout.write(self.style.SUCCESS("Summary:"))
            self.stdout.write(f"  Subnets to sync: {len(netuids)}")
            self.stdout.write(f"  Total blocks to sync: {total_tasks}")
            self.stdout.write(f"  Block range: {from_block} -> {to_block}")
            self.stdout.write(f"  Step: {step}")

            # Time estimation
            if time_per_block is not None and total_tasks > 0:
                total_seconds = total_tasks * time_per_block
                days = int(total_seconds // 86400)
                hours = int((total_seconds % 86400) // 3600)
                minutes = int((total_seconds % 3600) // 60)

                time_parts = []
                if days > 0:
                    time_parts.append(f"{days}d")
                if hours > 0:
                    time_parts.append(f"{hours}h")
                if minutes > 0 or not time_parts:
                    time_parts.append(f"{minutes}m")

                self.stdout.write(
                    f"  Estimated time: {' '.join(time_parts)} (at {time_per_block}s per block)",
                )

            self.stdout.write("")

            # Display per-subnet breakdown
            self.stdout.write("Per-subnet breakdown:")
            for uid in netuids:
                blocks = subnet_blocks[uid]
                if blocks:
                    self.stdout.write(
                        f"  Subnet {uid}: {len(blocks)} blocks (first: {blocks[0]}, last: {blocks[-1]})",
                    )
                else:
                    self.stdout.write(f"  Subnet {uid}: 0 blocks")

            return

        if use_async:
            self._process_async(from_block, to_block, netuids, network, lite, step, batch_size, batch_delay)
        else:
            self._process_synchronously(from_block, to_block, netuids, network, lite, step)

    def _process_synchronously(
        self,
        from_block: int,
        to_block: int,
        netuids: list[int],
        network: str,
        lite: bool,
        step: int,
    ) -> None:
        """Process blocks synchronously using native bittensor SDK."""
        self.stdout.write("Calculating dumpable blocks...")

        # Build list of (block, netuid) pairs to process
        tasks: list[tuple[int, int]] = []
        for netuid in netuids:
            dumpable_blocks = _get_epoch_start_blocks_in_range(from_block, to_block, netuid)
            tasks.extend((block_num, netuid) for block_num in dumpable_blocks[::step])

        total_tasks = len(tasks)
        self.stdout.write(f"Total dumpable blocks: {total_tasks} across {len(netuids)} subnets")
        self.stdout.write(f"Connecting to {network}...")

        processed = 0
        errors = 0

        self.stdout.write("Starting backfill...")
        self.stdout.write("Press Ctrl+C to stop gracefully...")

        try:
            # Connect to bittensor network
            subtensor = bt.Subtensor(network=network)
            self.stdout.write(self.style.SUCCESS(f"Connected to {subtensor.network}"))

            for block_num, netuid in tasks:
                try:
                    started_at = datetime.now(UTC)

                    # Fetch metagraph using native bittensor SDK (with fallback for historical blocks)
                    t1 = time.time()
                    metagraph = _get_metagraph_with_fallback(subtensor, netuid, block_num, lite=lite)
                    fetch_time = time.time() - t1

                    finished_at = datetime.now(UTC)

                    if metagraph is None or len(metagraph.uids) == 0:
                        self.stderr.write(f"No metagraph data for block {block_num}, netuid {netuid}")
                        errors += 1
                        continue

                    # Skip timestamp for fast backfill - it's optional for APY calculation
                    # and fetching it for each historical block is slow
                    block_timestamp: datetime | None = None

                    # Sync to database using APY-optimized service
                    t2 = time.time()
                    dump_metadata = DumpMetadata(
                        netuid=netuid,
                        epoch_position=_get_epoch_position_str(block_num, netuid),
                        started_at=started_at,
                        finished_at=finished_at,
                    )
                    sync_service = APYSyncService()
                    stats = sync_service.sync_metagraph(
                        metagraph=metagraph,
                        block_number=block_num,
                        block_timestamp=block_timestamp,
                        dump_metadata=dump_metadata,
                    )
                    sync_time = time.time() - t2

                    processed += 1
                    self.stdout.write(
                        f"[{processed}/{total_tasks}] Block {block_num} netuid {netuid}: "
                        f"fetch={fetch_time:.2f}s, sync={sync_time:.2f}s, "
                        f"neurons={stats['snapshots']}, dividends={stats['mechanism_metrics']}",
                    )

                except Exception as e:
                    errors += 1
                    logger.exception(
                        "Error processing block",
                        block=block_num,
                        netuid=netuid,
                        error=str(e),
                    )
                    self.stderr.write(
                        self.style.ERROR(f"Error at block {block_num}, netuid {netuid}: {e}"),
                    )

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrupted by user"))

        self.stdout.write(self.style.SUCCESS(f"\nCompleted: {processed} tasks, {errors} errors"))

    def _process_async(
        self,
        from_block: int,
        to_block: int,
        netuids: list[int],
        network: str,
        lite: bool,
        step: int,
        batch_size: int,
        batch_delay: float,
    ) -> None:
        """Dispatch Celery batch tasks for parallel processing."""
        from apps.metagraph.tasks import fast_apy_sync_batch  # type: ignore[attr-defined]

        self.stdout.write("Calculating dumpable blocks...")

        # Build list of (block, netuid) pairs to process
        all_blocks: list[tuple[int, int]] = []
        for netuid in netuids:
            dumpable_blocks = _get_epoch_start_blocks_in_range(from_block, to_block, netuid)
            all_blocks.extend((block_num, netuid) for block_num in dumpable_blocks[::step])

        total_blocks = len(all_blocks)
        self.stdout.write(f"Total dumpable blocks: {total_blocks} across {len(netuids)} subnets")

        # Split into batches for batch task processing
        batches = [all_blocks[i : i + batch_size] for i in range(0, len(all_blocks), batch_size)]
        total_batches = len(batches)
        self.stdout.write(f"Dispatching {total_batches} batch tasks (each with up to {batch_size} blocks)...")

        dispatched = 0
        errors = 0

        try:
            for i, batch in enumerate(batches, 1):
                try:
                    fast_apy_sync_batch.delay(
                        blocks=batch,
                        network=network,
                        lite=lite,
                    )
                    dispatched += 1
                    blocks_in_batch = len(batch)

                    self.stdout.write(f"Dispatched batch {i}/{total_batches} ({blocks_in_batch} blocks)")

                    # Apply delay between batches (except for the last one)
                    if i < total_batches and batch_delay > 0:
                        time.sleep(batch_delay)

                except Exception as e:
                    errors += 1
                    logger.exception(
                        "Error dispatching batch task",
                        batch_index=i,
                        blocks_count=len(batch),
                        error=str(e),
                    )
                    self.stderr.write(
                        self.style.ERROR(f"Error dispatching batch {i}: {e}"),
                    )

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrupted by user"))

        self.stdout.write(
            self.style.SUCCESS(f"\nDispatched: {dispatched} batch tasks ({total_blocks} blocks), {errors} errors")
        )
        self.stdout.write("Batch tasks are now running in Celery workers. Monitor with:")
        self.stdout.write("  docker compose logs -f celery-worker")
