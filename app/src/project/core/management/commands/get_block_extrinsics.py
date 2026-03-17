"""Fetch and display extrinsics from the current (or specified) block."""

from async_substrate_interface import SubstrateInterface
from django.conf import settings
from django.core.management.base import BaseCommand, CommandParser


DEFAULT_URL = "ws://127.0.0.1:9944"


class Command(BaseCommand):
    help = "Get extrinsics for the current block header (or a specific block number)."

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
        self.stdout.write(f"Connecting to {network}...")
        substrate = SubstrateInterface(url=network)

        block_number = options["block"]
        if block_number is not None:
            block_hash = substrate.get_block_hash(block_number)
            if not block_hash:
                self.stderr.write(self.style.ERROR(f"Block {block_number} not found"))
                return
        else:
            block_hash = None
            block_number = substrate.get_block_number(None)

        self.stdout.write(self.style.SUCCESS(f"Block #{block_number} (hash: {block_hash or 'latest'})"))

        block = substrate.get_block(block_hash=block_hash)
        extrinsics = block["block"]["extrinsics"]

        if not extrinsics:
            self.stdout.write("No extrinsics in this block.")
            return

        self.stdout.write(f"\nFound {len(extrinsics)} extrinsic(s):\n")
        for i, ext in enumerate(extrinsics):
            call = ext.value.get("call", {}) if hasattr(ext, "value") else ext.get("call", {})
            module = call.get("call_module", "?")
            function = call.get("call_function", "?")
            args = call.get("call_args", [])

            self.stdout.write(f"  [{i}] {module}.{function}")
            for arg in args:
                name = arg.get("name", "?")
                value = arg.get("value", "?")
                self.stdout.write(f"       {name}: {value}")
            self.stdout.write("")
