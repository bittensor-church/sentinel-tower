import signal
import time

import structlog
from django.conf import settings
from django.core.management.base import BaseCommand
from sentinel.v1.providers.base import BlockchainProvider
from sentinel.v1.providers.bittensor import bittensor_provider

from apps.metagraph.block_tasks import sync_metagraph_for_block
from apps.metagraph.services.metagraph_service import MetagraphService

logger = structlog.get_logger()

POLL_INTERVAL = 12  # seconds, matches bittensor block time


class Command(BaseCommand):
    help = "Long-running daemon that syncs metagraph snapshots from the blockchain using a persistent connection."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shutdown = False

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received shutdown signal", signal=sig_name)
        self._shutdown = True

    def _create_provider(self, provider_name: str) -> BlockchainProvider:
        if provider_name == "bittensor":
            provider = bittensor_provider()
        elif provider_name == "pylon":
            from sentinel.v1.providers.pylon import pylon_provider

            provider = pylon_provider(settings.PYLON_URL)
        else:
            raise ValueError(f"Unknown provider: {provider_name}")
        provider.__enter__()
        return provider

    def _close_provider(self, provider: BlockchainProvider) -> None:
        try:
            provider.__exit__(None, None, None)
        except Exception:
            logger.warning("Error closing provider", exc_info=True)

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            choices=["bittensor", "pylon"],
            default="bittensor",
            help="Blockchain provider to use for syncing (default: bittensor)",
        )

    def handle(self, *args, **options) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        provider_name = options["provider"]

        netuids = MetagraphService.netuids_to_sync()

        self.stdout.write("Starting sync_metagraph daemon...")
        logger.info("sync_metagraph daemon starting", poll_interval=POLL_INTERVAL, netuids=netuids)

        provider = self._create_provider(provider_name)
        last_processed_block = None

        try:
            while not self._shutdown:
                try:
                    head = provider.get_current_block()
                except Exception:
                    logger.warning("Connection error fetching head, reconnecting...", exc_info=True)
                    self._close_provider(provider)
                    provider = self._create_provider(provider_name)
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

                    dumpable_netuids = [
                        netuid for netuid in netuids if MetagraphService.is_dumpable_block(block_number, netuid)
                    ]

                    if not dumpable_netuids:
                        logger.debug("No subnets dumpable at block", block_number=block_number)
                        last_processed_block = block_number
                        continue

                    try:
                        for netuid in dumpable_netuids:
                            result = sync_metagraph_for_block(block_number, netuid, provider)
                            if result:
                                logger.info(
                                    "Metagraph synced",
                                    block=block_number,
                                    netuid=netuid,
                                    neurons=result["neurons"],
                                    weights=result["weights"],
                                    elapsed_ms=result["elapsed_ms"],
                                )
                            else:
                                logger.debug("No metagraph data", block=block_number, netuid=netuid)
                        last_processed_block = block_number
                    except Exception:
                        logger.warning(
                            "Error syncing metagraph, reconnecting...",
                            block_number=block_number,
                            exc_info=True,
                        )
                        self._close_provider(provider)
                        provider = self._create_provider(provider_name)
                        # Skip the failed block — backfill service will catch it
                        last_processed_block = block_number
                        break

                time.sleep(POLL_INTERVAL)
        finally:
            self._close_provider(provider)
            logger.info("sync_metagraph daemon stopped")
