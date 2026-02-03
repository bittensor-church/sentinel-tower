"""Backfill timestamps for historical blocks using calculated time delta."""

import os
from datetime import UTC, datetime, timedelta

import structlog
from django.core.management.base import BaseCommand
from django.db.models import Min
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from apps.metagraph.models import Block

logger = structlog.get_logger()

# Bittensor block time is 12 seconds
BLOCK_TIME_SECONDS = 12


class Command(BaseCommand):
    help = "Backfill timestamps for historical blocks using time delta calculation."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--from-timestamp",
            type=str,
            default=None,
            help="ISO format timestamp for the first block (e.g., 2024-01-15T00:00:00Z). "
            "If not provided, will fetch from archive node.",
        )
        parser.add_argument(
            "--from-block",
            type=int,
            default=None,
            help="Starting block number. If not provided, uses the smallest block in DB.",
        )
        parser.add_argument(
            "--to-block",
            type=int,
            default=None,
            help="Ending block number. If not provided, processes all blocks.",
        )
        parser.add_argument(
            "--network",
            type=str,
            default=None,
            help="Bittensor network URI for fetching initial timestamp (default: BITTENSOR_ARCHIVE_NETWORK)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of blocks to update per batch (default: 1000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without updating database",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Overwrite existing timestamps (default: only update NULL timestamps)",
        )

    def handle(self, *args, **options) -> None:
        from_timestamp_str = options["from_timestamp"]
        from_block = options["from_block"]
        to_block = options["to_block"]
        network = options["network"] or os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        overwrite = options["overwrite"]

        # Get block range from database
        if from_block is None:
            from_block = Block.objects.aggregate(min_block=Min("number"))["min_block"]
            if from_block is None:
                self.stderr.write(self.style.ERROR("No blocks found in database"))
                return

        # Get blocks to process
        blocks_qs = Block.objects.filter(number__gte=from_block).order_by("number")
        if to_block is not None:
            blocks_qs = blocks_qs.filter(number__lte=to_block)

        if not overwrite:
            blocks_qs = blocks_qs.filter(timestamp__isnull=True)

        total_blocks = blocks_qs.count()
        if total_blocks == 0:
            self.stdout.write(self.style.SUCCESS("No blocks need timestamp updates"))
            return

        # Get or calculate the reference timestamp
        reference_block = from_block
        reference_timestamp = None

        if from_timestamp_str:
            # Parse provided timestamp
            try:
                reference_timestamp = datetime.fromisoformat(from_timestamp_str.replace("Z", "+00:00"))
                if reference_timestamp.tzinfo is None:
                    reference_timestamp = reference_timestamp.replace(tzinfo=UTC)
            except ValueError as e:
                self.stderr.write(self.style.ERROR(f"Invalid timestamp format: {e}"))
                return
            self.stdout.write(f"Using provided timestamp: {reference_timestamp.isoformat()}")
        else:
            # Fetch timestamp from archive node
            self.stdout.write(f"Fetching timestamp for block {reference_block} from {network}...")
            try:
                reference_timestamp = self._fetch_block_timestamp(reference_block, network)
                if reference_timestamp is None:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Could not fetch timestamp for block {reference_block}. "
                            "Use --from-timestamp to provide it manually.",
                        ),
                    )
                    return
                self.stdout.write(
                    self.style.SUCCESS(f"Fetched timestamp: {reference_timestamp.isoformat()}"),
                )
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"Error fetching timestamp: {e}"))
                self.stderr.write("Use --from-timestamp to provide the timestamp manually.")
                return

        # Display summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("=== Timestamp Backfill ==="))
        self.stdout.write(f"  Reference block: {reference_block}")
        self.stdout.write(f"  Reference timestamp: {reference_timestamp.isoformat()}")
        self.stdout.write(f"  Blocks to update: {total_blocks}")
        self.stdout.write(f"  Block time: {BLOCK_TIME_SECONDS} seconds")
        self.stdout.write(f"  Batch size: {batch_size}")
        self.stdout.write(f"  Overwrite existing: {overwrite}")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN - No changes will be made ===\n"))
            # Show sample calculations
            sample_blocks = list(blocks_qs[:5].values_list("number", flat=True))
            self.stdout.write("Sample timestamp calculations:")
            for block_num in sample_blocks:
                delta_blocks = block_num - reference_block
                calculated_ts = reference_timestamp + timedelta(seconds=delta_blocks * BLOCK_TIME_SECONDS)
                self.stdout.write(f"  Block {block_num}: {calculated_ts.isoformat()}")
            if total_blocks > 5:
                self.stdout.write(f"  ... and {total_blocks - 5} more blocks")
            return

        # Process blocks in batches
        self.stdout.write("\nUpdating timestamps...")
        updated = 0
        errors = 0

        try:
            block_numbers = list(blocks_qs.values_list("number", flat=True))

            for i in range(0, len(block_numbers), batch_size):
                batch = block_numbers[i : i + batch_size]

                # Calculate timestamps for batch
                updates = []
                for block_num in batch:
                    delta_blocks = block_num - reference_block
                    calculated_ts = reference_timestamp + timedelta(seconds=delta_blocks * BLOCK_TIME_SECONDS)
                    updates.append((block_num, calculated_ts))

                # Bulk update
                for block_num, ts in updates:
                    Block.objects.filter(number=block_num).update(timestamp=ts)

                updated += len(batch)
                progress = (updated / total_blocks) * 100
                self.stdout.write(
                    f"  Updated {updated}/{total_blocks} blocks ({progress:.1f}%)",
                )

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrupted by user"))

        except Exception as e:
            errors += 1
            logger.exception("Error updating timestamps", error=str(e))
            self.stderr.write(self.style.ERROR(f"Error: {e}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Completed: {updated} blocks updated, {errors} errors"),
        )

    def _fetch_block_timestamp(self, block_number: int, network: str) -> datetime | None:
        """Fetch timestamp for a block from the network."""
        with bittensor_provider(network) as provider:
            service = sentinel_service(provider)
            block = service.ingest_block(block_number)
            if block.timestamp:
                # timestamp is in milliseconds
                return datetime.fromtimestamp(block.timestamp / 1000, tz=UTC)
        return None
