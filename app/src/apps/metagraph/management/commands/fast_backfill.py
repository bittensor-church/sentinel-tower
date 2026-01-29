"""Fast backfill command using sentinel SDK with archive node."""

import os
import time
from datetime import UTC, datetime

import structlog
from django.core.management.base import BaseCommand
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.sync_service import DumpMetadata, MetagraphSyncService
from apps.metagraph.tasks import fast_backfill_batch
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

logger = structlog.get_logger()


def _get_epoch_position_str(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch (start, inside, end)."""
    epoch = get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


def _get_dumpable_blocks_in_range(from_block: int, to_block: int, netuid: int) -> list[int]:
    """
    Get all dumpable blocks in a range for a given netuid.

    Iterates through epochs and collects dumpable blocks that fall within the range.
    """
    dumpable = set()
    current_block = from_block

    while current_block <= to_block:
        epoch = get_epoch_containing_block(current_block, netuid)
        epoch_dumpable = get_dumpable_blocks(epoch)

        for block in epoch_dumpable:
            if from_block <= block <= to_block:
                dumpable.add(block)

        # Move to the next epoch
        current_block = epoch.stop + 1

    return sorted(dumpable)


class Command(BaseCommand):
    help = "Fast backfill historical blocks using sentinel SDK with archive node."

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
            "--store-artifact",
            action="store_true",
            help="Store JSONL artifacts (slower but creates backup)",
        )
        parser.add_argument(
            "--use-celery",
            action="store_true",
            help="Spawn celery tasks for each block instead of processing synchronously",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Blocks per Celery task when using --use-celery (default: 10)",
        )
        parser.add_argument(
            "--batch-delay",
            type=float,
            default=1.0,
            help="Delay in seconds between spawning batch tasks (default: 1.0)",
        )

    def handle(self, *args, **options) -> None:
        from_block = options["from_block"]
        to_block = options["to_block"]
        netuid = options["netuid"]
        network = options["network"] or os.getenv("BITTENSOR_ARCHIVE_NETWORK")
        lite = options["lite"]
        step = options["step"]
        dry_run = options["dry_run"]
        store_artifact = options["store_artifact"]
        use_celery = options["use_celery"]
        batch_size = options["batch_size"]
        batch_delay = options["batch_delay"]

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
        self.stdout.write(f"Network: {network}, Subnets: {netuids}, Lite: {lite}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run mode: no data will be stored"))
            for uid in netuids:
                dumpable_blocks = _get_dumpable_blocks_in_range(from_block, to_block, uid)
                self.stdout.write(f"  Netuid {uid}: {len(dumpable_blocks)} dumpable blocks")
                for block_num in dumpable_blocks[::step]:
                    self.stdout.write(f"    Would process block {block_num}")
            return

        if use_celery:
            self._process_with_celery(
                from_block, to_block, netuids, network, lite, step, store_artifact, batch_size, batch_delay,
            )
        else:
            self._process_synchronously(from_block, to_block, netuids, network, lite, step, store_artifact)

    def _process_synchronously(
        self,
        from_block: int,
        to_block: int,
        netuids: list[int],
        network: str,
        lite: bool,
        step: int,
        store_artifact: bool,
    ) -> None:
        """Process blocks synchronously using a single provider connection."""
        self.stdout.write("Calculating dumpable blocks...")

        # Build list of (block, netuid) pairs to process
        tasks: list[tuple[int, int]] = []
        for netuid in netuids:
            dumpable_blocks = _get_dumpable_blocks_in_range(from_block, to_block, netuid)
            self.stdout.write(f"  Netuid {netuid}: {len(dumpable_blocks)} dumpable blocks")
            tasks.extend((block_num, netuid) for block_num in dumpable_blocks[::step])

        total_tasks = len(tasks)
        self.stdout.write(f"Total tasks: {total_tasks}")
        self.stdout.write(f"Connecting to {network}...")

        processed = 0
        errors = 0

        self.stdout.write("Starting backfill...")
        self.stdout.write("Press Ctrl+C to stop gracefully...")

        try:
            # Use single provider connection for all blocks
            with bittensor_provider(network) as provider:
                service = sentinel_service(provider)
                self.stdout.write(self.style.SUCCESS("Connected"))

                for block_num, netuid in tasks:
                    try:
                        started_at = datetime.now(UTC)

                        # Fetch metagraph using sentinel SDK (skip_timestamp for faster backfill)
                        t1 = time.time()
                        subnet = service.ingest_subnet(netuid, block_num, lite=lite, skip_timestamp=True)
                        metagraph = subnet.metagraph
                        fetch_time = time.time() - t1

                        finished_at = datetime.now(UTC)

                        if not metagraph:
                            self.stderr.write(f"No metagraph data for block {block_num}, netuid {netuid}")
                            errors += 1
                            continue

                        # Optionally store artifact
                        if store_artifact:
                            MetagraphService.store_metagraph_artifact(metagraph)

                        # Sync to database using Pydantic model directly (avoids model_dump() overhead)
                        t2 = time.time()
                        dump_metadata = DumpMetadata(
                            netuid=netuid,
                            epoch_position=_get_epoch_position_str(block_num, netuid),
                            started_at=started_at,
                            finished_at=finished_at,
                        )
                        sync_service = MetagraphSyncService()
                        stats = sync_service.sync_from_model(metagraph, dump_metadata)
                        sync_time = time.time() - t2

                        processed += 1
                        self.stdout.write(
                            f"[{processed}/{total_tasks}] Block {block_num} netuid {netuid}: "
                            f"fetch={fetch_time:.2f}s, sync={sync_time:.2f}s, "
                            f"neurons={stats['neurons']}, weights={stats['weights']}",
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

    def _process_with_celery(
        self,
        from_block: int,
        to_block: int,
        netuids: list[int],
        network: str,
        lite: bool,
        step: int,
        store_artifact: bool,
        batch_size: int,
        batch_delay: float,
    ) -> None:
        """Spawn celery tasks for parallel processing using batches."""

        self.stdout.write("Calculating dumpable blocks...")

        # Build list of (block, netuid) pairs to process
        all_tasks: list[tuple[int, int]] = []
        for netuid in netuids:
            dumpable_blocks = _get_dumpable_blocks_in_range(from_block, to_block, netuid)
            self.stdout.write(f"  Netuid {netuid}: {len(dumpable_blocks)} dumpable blocks")
            all_tasks.extend((block_num, netuid) for block_num in dumpable_blocks[::step])

        # Split into batches
        batches = [all_tasks[i : i + batch_size] for i in range(0, len(all_tasks), batch_size)]

        self.stdout.write(
            f"Total blocks: {len(all_tasks)}, Batches: {len(batches)} (size={batch_size}, delay={batch_delay}s)",
        )
        self.stdout.write("Spawning batch tasks...")

        for batch in batches:
            time.sleep(batch_delay)
            fast_backfill_batch.delay(
                blocks=list(batch),
                network=network,
                lite=lite,
                store_artifact=store_artifact,
            )  # type: ignore

        self.stdout.write(self.style.SUCCESS(f"Spawned {len(batches)} batch tasks"))
        self.stdout.write("Monitor progress with: celery -A project inspect active")
