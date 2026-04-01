import os
import signal
import time
from collections.abc import Callable

import structlog
from django.core.management.base import BaseCommand
from sentinel.v1.providers.bittensor import bittensor_provider

from apps.extrinsics.block_tasks import store_block_extrinsics
from apps.extrinsics.models import Extrinsic
from project.core.utils import get_archive_provider

logger = structlog.get_logger()

DEFAULT_LOOKBACK = 12_000
DEFAULT_RATE_LIMIT = 1.0


def _get_lookback_default() -> int:
    return int(os.environ.get("BACKFILL_LOOKBACK", DEFAULT_LOOKBACK))


def _get_rate_limit_default() -> float:
    return float(os.environ.get("BACKFILL_RATE_LIMIT", DEFAULT_RATE_LIMIT))


def _find_missing_blocks(lookback: int) -> list[int]:
    with bittensor_provider() as provider:
        head = provider.get_current_block()
    max_block = head - 300
    min_block = max_block - lookback

    logger.info(
        "Scanning for missing extrinsic blocks",
        min_block=min_block,
        max_block=max_block,
        lookback=lookback,
    )

    existing = set(
        Extrinsic.objects.filter(block_number__gte=min_block, block_number__lte=max_block)
        .values_list("block_number", flat=True)
        .distinct()
    )
    expected = set(range(min_block, max_block + 1))
    return sorted(expected - existing)


def _backfill_blocks(blocks: list[int], rate_limit: float, should_stop: Callable[[], bool]) -> tuple[int, int]:
    synced = 0
    errors = 0
    with get_archive_provider() as provider:
        for i, block_number in enumerate(blocks):
            if should_stop():
                logger.info("Shutdown requested, stopping.")
                break

            try:
                result = store_block_extrinsics(block_number, provider)
                synced += 1
                logger.info(
                    "Backfilled block",
                    block_number=block_number,
                    result=result or "no extrinsics",
                    remaining=len(blocks) - i - 1,
                )
            except Exception:
                errors += 1
                logger.warning("Error backfilling block", block_number=block_number, exc_info=True)

            if rate_limit > 0 and i < len(blocks) - 1:
                time.sleep(rate_limit)

    return synced, errors


class Command(BaseCommand):
    help = "Backfill missing extrinsics by scanning for gaps between head and head-lookback."

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
        parser.add_argument(
            "--block",
            type=int,
            default=None,
            help="Specific block number to backfill (skips gap detection)",
        )

    def handle(self, *args, **options):
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        rate_limit = options["rate_limit"] if options["rate_limit"] is not None else _get_rate_limit_default()

        if options["block"] is not None:
            missing = [options["block"]]
            logger.info("Backfilling specific block", block_number=options["block"])
        else:
            lookback = options["lookback"] if options["lookback"] is not None else _get_lookback_default()
            missing = _find_missing_blocks(lookback)
            if not missing:
                self.stdout.write("No missing blocks found.")
                return
            self.stdout.write(f"Found {len(missing)} missing blocks.")
            logger.info("Missing blocks detected", count=len(missing), first=missing[0], last=missing[-1])

        synced, errors = _backfill_blocks(missing, rate_limit, lambda: self._shutdown)

        self.stdout.write(f"Done. Synced: {synced}, errors: {errors}, total: {len(missing)}.")
        logger.info("Backfill complete", synced=synced, errors=errors, total=len(missing))
