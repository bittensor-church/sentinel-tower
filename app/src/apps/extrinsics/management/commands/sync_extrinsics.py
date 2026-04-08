import signal
import time

import structlog
from django.core.management.base import BaseCommand
from sentinel.v1.providers.base import BlockchainProvider
from sentinel.v1.providers.bittensor import bittensor_provider

from apps.extrinsics.block_tasks import store_block_extrinsics

logger = structlog.get_logger()

POLL_INTERVAL = 12  # seconds, matches bittensor block time


class Command(BaseCommand):
    help = "Long-running daemon that syncs extrinsics from the blockchain using a persistent connection."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received shutdown signal", signal=sig_name)
        self._shutdown = True

    def _create_provider(self) -> BlockchainProvider:
        provider = bittensor_provider()
        provider.__enter__()
        return provider

    def _close_provider(self, provider: BlockchainProvider) -> None:
        try:
            provider.__exit__(None, None, None)
        except Exception:
            logger.warning("Error closing provider", exc_info=True)

    def handle(self, *args, **options) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        self.stdout.write("Starting sync_extrinsics daemon...")
        logger.info("sync_extrinsics daemon starting", poll_interval=POLL_INTERVAL)

        provider = self._create_provider()
        last_processed_block = None

        try:
            while not self._shutdown:
                try:
                    head = provider.get_current_block()
                except Exception:
                    logger.warning("Connection error fetching head, reconnecting...", exc_info=True)
                    self._close_provider(provider)
                    provider = self._create_provider()
                    continue

                if last_processed_block is None:
                    last_processed_block = head - 1
                    logger.info("Starting from head", head=head)

                if head <= last_processed_block:
                    time.sleep(POLL_INTERVAL)
                    continue

                # Process all blocks from last_processed + 1 to head
                for block_number in range(last_processed_block + 1, head + 1):
                    if self._shutdown:
                        break
                    try:
                        result = store_block_extrinsics(block_number, provider)
                        if result:
                            logger.info(
                                "Extrinsics synced",
                                block=block_number,
                                extrinsics=result["db_count"],
                                elapsed_ms=result["elapsed_ms"],
                            )
                        else:
                            logger.debug("Block processed (no extrinsics)", block=block_number)
                        last_processed_block = block_number
                    except Exception:
                        logger.warning(
                            "Error processing block, reconnecting...", block_number=block_number, exc_info=True
                        )
                        self._close_provider(provider)
                        provider = self._create_provider()
                        # Skip the failed block — backfill service will catch it
                        last_processed_block = block_number
                        break

                time.sleep(POLL_INTERVAL)
        finally:
            self._close_provider(provider)
            logger.info("sync_extrinsics daemon stopped")
