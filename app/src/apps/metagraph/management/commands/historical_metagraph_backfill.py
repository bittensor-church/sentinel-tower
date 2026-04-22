import os
import signal
import time

import structlog
from django.core.management.base import BaseCommand, CommandError

from apps.metagraph.block_tasks import sync_metagraph_for_block
from apps.metagraph.models import MetagraphDump
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.utils import epoch_start_blocks_in_range
from project.core.utils import get_archive_provider

logger = structlog.get_logger()

DEFAULT_RATE_LIMIT = 1.0
DEFAULT_SLEEP_SECONDS = 3600
DEFAULT_BLOCK_RANGE = 2_000_000


def _parse_netuids(value: str) -> list[int]:
    return [int(x.strip()) for x in value.split(",") if x.strip()]


class Command(BaseCommand):
    help = (
        "Daemon: backfill one lite metagraph snapshot per epoch from "
        "HISTORICAL_BACKFILL_BLOCK_START to HISTORICAL_BACKFILL_BLOCK_END "
        "(default: start + 2,000,000), oldest-first, using a single archive "
        "websocket connection per pass. Sleeps and re-runs after each pass "
        "to retry any failed fetches."
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received shutdown signal, finishing current block...", signal=sig_name)
        self._shutdown = True

    def _interruptible_sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while not self._shutdown and time.monotonic() < end:
            time.sleep(min(1.0, end - time.monotonic()))

    def add_arguments(self, parser):
        parser.add_argument("--block-start", type=int, default=None)
        parser.add_argument("--block-end", type=int, default=None)
        parser.add_argument("--rate-limit", type=float, default=None)
        parser.add_argument("--sleep-seconds", type=float, default=None)
        parser.add_argument("--netuids", type=str, default=None, help="CSV of netuids")
        parser.add_argument(
            "--force-refresh",
            action="store_true",
            default=None,
            help=(
                "Re-fetch every (block, netuid) in range, ignoring MetagraphDump dedup. "
                "Use to refresh existing rows after schema changes (e.g. new fields). "
                "Env: HISTORICAL_BACKFILL_FORCE_REFRESH=1"
            ),
        )

    def handle(self, *args, **options):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        block_start_raw = options["block_start"] or os.environ.get("HISTORICAL_BACKFILL_BLOCK_START")
        if not block_start_raw:
            raise CommandError("HISTORICAL_BACKFILL_BLOCK_START env (or --block-start) is required")
        block_start = int(block_start_raw)

        block_end_raw = options["block_end"] or os.environ.get("HISTORICAL_BACKFILL_BLOCK_END")
        block_end = int(block_end_raw) if block_end_raw else block_start + DEFAULT_BLOCK_RANGE
        if block_end < block_start:
            raise CommandError(f"block_end ({block_end}) must be >= block_start ({block_start})")

        rate_limit = (
            options["rate_limit"]
            if options["rate_limit"] is not None
            else float(os.environ.get("HISTORICAL_BACKFILL_RATE_LIMIT", DEFAULT_RATE_LIMIT))
        )
        sleep_seconds = (
            options["sleep_seconds"]
            if options["sleep_seconds"] is not None
            else float(os.environ.get("HISTORICAL_BACKFILL_SLEEP_SECONDS", DEFAULT_SLEEP_SECONDS))
        )
        netuids_raw = options["netuids"] or os.environ.get("HISTORICAL_BACKFILL_NETUIDS")
        netuids: list[int] = _parse_netuids(netuids_raw) if netuids_raw else MetagraphService.netuids_to_sync()

        force_refresh = (
            options["force_refresh"]
            if options["force_refresh"] is not None
            else os.environ.get("HISTORICAL_BACKFILL_FORCE_REFRESH", "").lower() in ("1", "true", "yes")
        )

        logger.info(
            "Historical metagraph backfill daemon starting",
            block_start=block_start,
            block_end=block_end,
            netuids=netuids,
            rate_limit=rate_limit,
            sleep_seconds=sleep_seconds,
            force_refresh=force_refresh,
        )

        while not self._shutdown:
            self._run_pass(block_start, block_end, netuids, rate_limit, force_refresh=force_refresh)
            if self._shutdown:
                break
            logger.info("Pass complete, sleeping", sleep_seconds=sleep_seconds)
            self._interruptible_sleep(sleep_seconds)

        logger.info("Historical metagraph backfill daemon stopped")

    def _run_pass(
        self,
        block_start: int,
        block_end: int,
        netuids: list[int],
        rate_limit: float,
        *,
        force_refresh: bool = False,
    ) -> None:
        missing: list[tuple[int, int]] = []
        for netuid in netuids:
            expected = epoch_start_blocks_in_range(block_start, block_end, netuid)
            if not expected:
                continue
            if force_refresh:
                for block_number in expected:
                    missing.append((block_number, netuid))
                continue
            existing = set(
                MetagraphDump.objects.filter(
                    netuid=netuid,
                    block_id__gte=block_start,
                    block_id__lte=block_end,
                ).values_list("block_id", flat=True)
            )
            for block_number in expected:
                if block_number not in existing:
                    missing.append((block_number, netuid))

        if not missing:
            logger.info("No missing epoch-start dumps", block_start=block_start, block_end=block_end)
            return

        missing.sort()

        logger.info("Found missing epoch-start dumps", count=len(missing), block_start=block_start, block_end=block_end)

        synced = 0
        errors = 0
        with get_archive_provider() as provider:
            for i, (block_number, netuid) in enumerate(missing):
                if self._shutdown:
                    logger.info("Shutdown requested, stopping pass.")
                    break
                try:
                    result = sync_metagraph_for_block(block_number, netuid, provider, lite=True)
                    synced += 1
                    remaining = len(missing) - i - 1
                    if result:
                        logger.info(
                            "Backfilled epoch-start metagraph",
                            block=block_number,
                            netuid=netuid,
                            neurons=result["neurons"],
                            elapsed_ms=result["elapsed_ms"],
                            remaining=remaining,
                        )
                    else:
                        logger.debug(
                            "Backfilled epoch-start metagraph (empty)",
                            block=block_number,
                            netuid=netuid,
                            remaining=remaining,
                        )
                except Exception:
                    errors += 1
                    logger.warning(
                        "Error backfilling epoch-start metagraph",
                        block_number=block_number,
                        netuid=netuid,
                        exc_info=True,
                    )

                if rate_limit > 0 and i < len(missing) - 1 and not self._shutdown:
                    time.sleep(rate_limit)

        logger.info("Pass finished", synced=synced, errors=errors, total=len(missing))
