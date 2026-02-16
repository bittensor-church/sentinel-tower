"""Submit test extrinsics to a local bittensor node for development testing.

Submits real on-chain extrinsics that the block scheduler will pick up
and process through the notification pipeline.

Requires a running localnet node (e.g., ws://127.0.0.1:9944) with
the //Alice account as sudo.
"""

import time

from async_substrate_interface import SubstrateInterface
from bittensor import Keypair
from django.core.management.base import BaseCommand

DEFAULT_URL = "ws://127.0.0.1:9944"


class Command(BaseCommand):
    help = "Submit test extrinsics (sudo, register_network, dissolve_network, coldkey_swap) to a local bittensor node."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--url",
            type=str,
            default=None,
            help=f"Node WebSocket URL (default: settings.BITTENSOR_NETWORK or {DEFAULT_URL})",
        )
        parser.add_argument(
            "--type",
            type=str,
            default="all",
            choices=["sudo", "register", "dissolve", "coldkey_swap", "all"],
            help="Type of extrinsic to submit (default: all)",
        )
        parser.add_argument(
            "--netuid",
            type=int,
            default=None,
            help="Subnet UID to dissolve (overrides auto-detected netuid from register)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2.0,
            help="Delay in seconds between extrinsics (default: 2.0)",
        )

    def handle(self, *args, **options) -> None:
        url = options["url"] or DEFAULT_URL
        extrinsic_type = options["type"]
        delay = options["delay"]

        self.stdout.write(f"Connecting to {url}...")
        substrate = SubstrateInterface(url=url)
        self.stdout.write(self.style.SUCCESS(f"Connected. Current block: {substrate.get_block_number(None)}"))

        alice = Keypair.create_from_uri("//Alice")
        bob = Keypair.create_from_uri("//Bob")

        self._topup_balance(substrate, alice, bob)

        self._registered_netuid = options["netuid"]

        actions = {
            "sudo": self._submit_sudo_call,
            "register": self._submit_register_network,
            "dissolve": self._submit_dissolve_network,
            "coldkey_swap": self._submit_coldkey_swap,
        }

        if extrinsic_type == "all":
            types_to_run = ["sudo", "register", "dissolve", "coldkey_swap"]
        else:
            types_to_run = [extrinsic_type]

        succeeded = 0
        for i, t in enumerate(types_to_run):
            if i > 0:
                self.stdout.write(f"Waiting {delay}s...")
                time.sleep(delay)
            try:
                actions[t](substrate, alice, bob)
                succeeded += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Failed: {e}"))

        self.stdout.write(self.style.SUCCESS(f"Done. {succeeded}/{len(types_to_run)} submitted."))

    def _topup_balance(self, substrate, alice, bob) -> None:
        """Force-set Alice's balance to 1M TAO via sudo so extrinsics don't fail from insufficient funds."""
        self.stdout.write("Topping up Alice's balance...")

        # Transfer a small amount from Bob to cover Alice's transaction fees
        transfer_call = substrate.compose_call(
            call_module="Balances",
            call_function="transfer_keep_alive",
            call_params={
                "dest": alice.ss58_address,
                "value": 1_000_000_000,  # 1 TAO for fees
            },
        )
        extrinsic = substrate.create_signed_extrinsic(call=transfer_call, keypair=bob)
        substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
        self.stdout.write(self.style.SUCCESS("  Transferred 1 TAO from Bob to cover fees"))

        # Now Alice can afford fees for the sudo call
        inner_call = substrate.compose_call(
            call_module="Balances",
            call_function="force_set_balance",
            call_params={
                "who": alice.ss58_address,
                "new_free": 1_000_000_000_000_000,  # 1M TAO in rao
            },
        )
        sudo_call = substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": inner_call},
        )
        extrinsic = substrate.create_signed_extrinsic(call=sudo_call, keypair=alice)
        result = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
        if getattr(result, "is_success", True):
            self.stdout.write(self.style.SUCCESS("  Alice balance set to 1,000,000 TAO"))
        else:
            self.stdout.write(self.style.WARNING("  Balance top-up may have failed, continuing anyway"))

    def _submit_extrinsic(self, substrate, extrinsic, label: str):
        """Submit an extrinsic and report the result."""
        self.stdout.write(f"Submitting {label}...")
        result = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
        block_hash = getattr(result, "block_hash", None)
        self.stdout.write(self.style.SUCCESS(f"  Included in block {block_hash}"))
        return result

    def _submit_sudo_call(self, substrate, alice, _bob) -> None:
        """Submit a Sudo call: sudo_set_min_burn on subnet 1."""
        call = substrate.compose_call(
            call_module="AdminUtils",
            call_function="sudo_set_min_burn",
            call_params={"netuid": 1, "min_burn": 1000},
        )
        sudo_call = substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": call},
        )
        extrinsic = substrate.create_signed_extrinsic(call=sudo_call, keypair=alice)
        self._submit_extrinsic(substrate, extrinsic, "Sudo → sudo_set_min_burn(netuid=1, min_burn=1000)")

    def _submit_register_network(self, substrate, alice, _bob) -> None:
        """Submit a register_network call and store the new netuid for dissolve."""
        call = substrate.compose_call(
            call_module="SubtensorModule",
            call_function="register_network",
            call_params={"hotkey": alice.ss58_address},
        )
        extrinsic = substrate.create_signed_extrinsic(call=call, keypair=alice)
        result = self._submit_extrinsic(substrate, extrinsic, "SubtensorModule → register_network")

        # Extract netuid from NetworkAdded event
        for event in getattr(result, "triggered_events", []):
            if getattr(event, "event_id", None) == "NetworkAdded":
                attrs = getattr(event, "attributes", None) or {}
                if isinstance(attrs, dict) and "netuid" in attrs:
                    self._registered_netuid = attrs["netuid"]
                    break

        if self._registered_netuid:
            self.stdout.write(self.style.SUCCESS(f"  Registered subnet netuid={self._registered_netuid}"))

    def _submit_dissolve_network(self, substrate, alice, _bob) -> None:
        """Submit a dissolve_network call via Sudo for the previously registered subnet."""
        netuid = self._registered_netuid
        if netuid is None:
            self.stdout.write(
                self.style.WARNING(
                    "  No netuid to dissolve (use --netuid or run with --type=all to register first), skipping"
                )
            )
            return

        inner_call = substrate.compose_call(
            call_module="SubtensorModule",
            call_function="dissolve_network",
            call_params={
                "coldkey": alice.ss58_address,
                "netuid": netuid,
            },
        )
        sudo_call = substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": inner_call},
        )
        extrinsic = substrate.create_signed_extrinsic(call=sudo_call, keypair=alice)
        self._submit_extrinsic(substrate, extrinsic, f"Sudo → dissolve_network(netuid={netuid})")

    def _submit_coldkey_swap(self, substrate, alice, bob) -> None:
        """Submit a swap_coldkey call via Sudo."""
        call = substrate.compose_call(
            call_module="SubtensorModule",
            call_function="swap_coldkey",
            call_params={
                "old_coldkey": alice.ss58_address,
                "new_coldkey": bob.ss58_address,
                "swap_cost": 0,
            },
        )
        sudo_call = substrate.compose_call(
            call_module="Sudo",
            call_function="sudo",
            call_params={"call": call},
        )
        extrinsic = substrate.create_signed_extrinsic(call=sudo_call, keypair=alice)
        self._submit_extrinsic(
            substrate, extrinsic, f"Sudo → swap_coldkey(old={alice.ss58_address[:8]}..., new={bob.ss58_address[:8]}...)"
        )
