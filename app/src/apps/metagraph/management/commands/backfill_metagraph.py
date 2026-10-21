import os
import signal
from math import isfinite
from threading import Event

import structlog
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from sentinel.v1.providers.bittensor import bittensor_provider

from apps.metagraph.block_tasks import sync_metagraph_for_block
from apps.metagraph.models import MetagraphDump
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.utils import get_dumpable_blocks_in_range
from project.core.utils import get_archive_provider

logger = structlog.get_logger()

DEFAULT_LOOKBACK = 12_000
DEFAULT_RATE_LIMIT = 1.0


def _get_lookback_default() -> int:
    return int(os.environ.get("BACKFILL_LOOKBACK", DEFAULT_LOOKBACK))


def _get_rate_limit_default() -> float:
    return float(os.environ.get("BACKFILL_RATE_LIMIT", DEFAULT_RATE_LIMIT))


class Command(BaseCommand):
    help = "Backfill missing metagraph dumps by scanning for gaps between head and head-lookback."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = Event()

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received shutdown signal, finishing current block...", signal=sig_name)
        self._shutdown.set()

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
        parser.add_argument(
            "--interval",
            type=float,
            default=0,
            help="Seconds between scans; 0 runs once. Repeat mode only repairs history after each subnet's first dump.",
        )
        parser.add_argument(
            "--settle-blocks",
            type=int,
            default=300,
            help="Leave this many newest blocks to live ingestion (default: 300; automatic repair uses 25).",
        )

    def handle(self, *args, **options):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        lookback: int = options["lookback"] if options["lookback"] is not None else _get_lookback_default()
        rate_limit: float = options["rate_limit"] if options["rate_limit"] is not None else _get_rate_limit_default()
        interval: float = options["interval"]
        settle_blocks: int = options["settle_blocks"]
        if lookback <= 0 or settle_blocks <= 0:
            raise CommandError("lookback and settle-blocks must be positive")
        if any(not isfinite(value) or value < 0 for value in (rate_limit, interval)):
            raise CommandError("rate-limit and interval must be finite and non-negative")

        while not self._shutdown.is_set():
            try:
                self._scan(lookback, rate_limit, settle_blocks, automatic=interval > 0)
            except Exception:
                if interval == 0:
                    raise
                # Opening a provider and reading head can fail before any per-dump
                # retry handling. Keep the background repair service alive too.
                logger.exception("Metagraph repair scan failed; will retry", interval=interval)
            finally:
                if interval > 0:
                    close_old_connections()
            if interval == 0 or self._shutdown.wait(interval):
                break

    def _scan(self, lookback: int, rate_limit: float, settle_blocks: int, *, automatic: bool) -> None:
        netuids = MetagraphService.netuids_to_sync()

        with bittensor_provider() as provider:
            head = provider.get_current_block()
        if self._shutdown.is_set():
            return
        max_block = head - settle_blocks
        min_block = max(0, max_block - lookback)

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
            start = min_block
            if automatic:
                # New installations/subnets must not bootstrap a day of history.
                # Include unfinished first dumps, so a crash mid-dump is repairable.
                first_block = (
                    MetagraphDump.objects.filter(netuid=netuid)
                    .order_by("block_id")
                    .values_list("block_id", flat=True)
                    .first()
                )
                if first_block is None:
                    continue
                start = max(start, first_block)
            expected = get_dumpable_blocks_in_range(start, max_block, netuid)
            existing = set(
                MetagraphDump.objects.filter(
                    netuid=netuid,
                    block_id__gte=start,
                    block_id__lte=max_block,
                    finished_at__isnull=False,
                ).values_list("block_id", flat=True)
            )
            for block_number in sorted(expected - existing):
                missing.append((block_number, netuid))
        missing.sort()

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
                if self._shutdown.is_set():
                    self.stdout.write("Shutdown requested, stopping.")
                    break

                # Live ingestion or a manual repair may have completed it since
                # the scan. Avoid rewriting those completed dumps.
                if MetagraphDump.objects.filter(
                    netuid=netuid, block_id=block_number, finished_at__isnull=False
                ).exists():
                    continue

                try:
                    result = sync_metagraph_for_block(block_number, netuid, provider)
                    remaining = len(missing) - i - 1
                    if result:
                        synced += 1
                        logger.info(
                            "Backfilled metagraph",
                            block=block_number,
                            netuid=netuid,
                            neurons=result["neurons"],
                            weights=result["weights"],
                            elapsed_ms=result["elapsed_ms"],
                            remaining=remaining,
                        )
                    else:
                        errors += 1
                        logger.warning(
                            "No metagraph returned; dump remains missing",
                            block=block_number,
                            netuid=netuid,
                            remaining=remaining,
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
                    if self._shutdown.wait(rate_limit):
                        break

        self.stdout.write(f"Done. Synced: {synced}, errors: {errors}, total: {len(missing)}.")
        logger.info("Metagraph backfill complete", synced=synced, errors=errors, total=len(missing))
