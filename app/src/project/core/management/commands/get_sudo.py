"""Retrieve the Sudo key from the chain."""

from async_substrate_interface import SubstrateInterface
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser

DEFAULT_URL = "ws://127.0.0.1:9944"

NETWORK_URLS = {
    "finney": "wss://entrypoint-finney.opentensor.ai:443",
    "test": "wss://test.finney.opentensor.ai:443",
    "local": "ws://127.0.0.1:9944",
}


class Command(BaseCommand):
    help = "Get the Sudo key from the chain."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--url",
            type=str,
            default=None,
            help=f"Node WebSocket URL (default: settings.BITTENSOR_NETWORK or {DEFAULT_URL})",
        )
        parser.add_argument(
            "--block",
            type=int,
            default=None,
            help="Block number to query (default: latest finalized block)",
        )

    def handle(self, *args, **options) -> None:
        network = options["url"] or getattr(settings, "BITTENSOR_NETWORK", DEFAULT_URL)
        url = NETWORK_URLS.get(network, network)

        self.stdout.write(f"Connecting to {url}...")
        substrate = SubstrateInterface(url=url)

        block_hash = None
        if options["block"] is not None:
            block_hash = substrate.get_block_hash(options["block"])
            if not block_hash:
                self.stderr.write(self.style.ERROR(f"Block {options['block']} not found"))
                return

        block_number = options["block"] or substrate.get_block_number(None)
        self.stdout.write(f"Block #{block_number}\n")

        result = substrate.query("Sudo", "Key", block_hash=block_hash)

        if result is None:
            self.stderr.write(self.style.ERROR("Sudo key not found"))
            return

        self.stdout.write(f"Sudo key: {result}")
