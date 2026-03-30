import os
import signal
import time

import structlog
from django.core.management.base import BaseCommand
from sentinel.v1.providers.bittensor import bittensor_provider

from apps.metagraph.block_tasks import sync_metagraph_for_block
from apps.metagraph.models import MetagraphDump
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block
from project.core.utils import get_archive_provider

logger = structlog.get_logger()

DEFAULT_LOOKBACK = 12_000
DEFAULT_RATE_LIMIT = 1.0


def _get_lookback_default() -> int:
    return int(os.environ.get("BACKFILL_LOOKBACK", DEFAULT_LOOKBACK))


def _get_rate_limit_default() -> float:
    return float(os.environ.get("BACKFILL_RATE_LIMIT", DEFAULT_RATE_LIMIT))


def _get_dumpable_blocks_in_range(min_block: int, max_block: int, netuid: int) -> set[int]:
    """Get all dumpable block numbers for a netuid within a range."""
    dumpable = set()
    block = min_block
    while block <= max_block:
        epoch = get_epoch_containing_block(block, netuid)
        for b in get_dumpable_blocks(epoch):
            if min_block <= b <= max_block:
                dumpable.add(b)
        # Jump to next epoch
        block = epoch.stop
    return dumpable


class Command(BaseCommand):
    help = "Backfill missing metagraph dumps by scanning for gaps between head and head-lookback."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received shutdown signal, finishing current block...", signal=sig_name)
        self._shutdown = True

    def add_arguments(self, parser):
        parser.add_argument(
            "--lookback",
            type=int,
            default=None,
            help="Number of blocks behind head to scan for gaps (default: BACKFILL_LOOKBACK env or 12000)",
        )
        parser.add_argument(
            "--rate-limit",
            type=float,
            default=None,
            help="Seconds to sleep between blocks (default: BACKFILL_RATE_LIMIT env or 1.0)",
        )

    def handle(self, *args, **options):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        lookback: int = options["lookback"] if options["lookback"] is not None else _get_lookback_default()
        rate_limit: float = options["rate_limit"] if options["rate_limit"] is not None else _get_rate_limit_default()

        netuids = MetagraphService.netuids_to_sync()

        # Determine scan range: [head - 300 - lookback, head - 300]
        with bittensor_provider() as provider:
            head = provider.get_current_block()
        max_block = head - 300
        min_block = max_block - lookback

        logger.info(
            "Scanning for missing metagraph dumps",
            min_block=min_block,
            max_block=max_block,
            lookback=lookback,
            rate_limit=rate_limit,
            netuids=netuids,
        )

        # Find missing (block, netuid) pairs
        missing: list[tuple[int, int]] = []
        for netuid in netuids:
            expected = _get_dumpable_blocks_in_range(min_block, max_block, netuid)
            existing = set(
                MetagraphDump.objects.filter(
                    netuid=netuid,
                    block_id__gte=min_block,
                    block_id__lte=max_block,
                ).values_list("block_id", flat=True)
            )
            for block_number in sorted(expected - existing):
                missing.append((block_number, netuid))

        if not missing:
            self.stdout.write("No missing metagraph dumps found.")
            logger.info("No missing metagraph dumps found", min_block=min_block, max_block=max_block)
            return

        self.stdout.write(f"Found {len(missing)} missing metagraph dumps (range {min_block}-{max_block}).")
        logger.info("Missing metagraph dumps detected", count=len(missing))

        # Backfill using archive node
        synced = 0
        errors = 0
        with get_archive_provider() as provider:
            for i, (block_number, netuid) in enumerate(missing):
                if self._shutdown:
                    self.stdout.write("Shutdown requested, stopping.")
                    break

                try:
                    result = sync_metagraph_for_block(block_number, netuid, provider)
                    synced += 1
                    logger.info(
                        "Backfilled metagraph",
                        block_number=block_number,
                        netuid=netuid,
                        result=result or "no metagraph",
                        remaining=len(missing) - i - 1,
                    )
                except Exception:
                    errors += 1
                    logger.warning(
                        "Error backfilling metagraph",
                        block_number=block_number,
                        netuid=netuid,
                        exc_info=True,
                    )

                if rate_limit > 0 and i < len(missing) - 1:
                    time.sleep(rate_limit)

        self.stdout.write(f"Done. Synced: {synced}, errors: {errors}, total: {len(missing)}.")
        logger.info("Metagraph backfill complete", synced=synced, errors=errors, total=len(missing))
