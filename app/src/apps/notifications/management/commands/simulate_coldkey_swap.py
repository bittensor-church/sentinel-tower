"""Simulate a coldkey-swap notification and route it to per-subnet Discord webhooks.

Bypasses ColdkeySwapNotification's role resolution by pre-enriching synthetic
extrinsics with explicit netuids, then calls SubnetRoutedNotification.notify
directly so the real routing path (DatabaseWebhookChannel lookup, payload
format, HTTP POST) runs end-to-end against existing rows in subnet_webhooks.

Usage (inside docker):
    docker compose run --rm app python manage.py simulate_coldkey_swap
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.metagraph.models import Coldkey
from apps.metagraph.services.coldkey_roles import ColdkeyRoles
from apps.notifications.base import SubnetRoutedNotification
from apps.notifications.handlers.coldkey_swap import ColdkeySwapNotification
from apps.notifications.models import SubnetWebhook

SIM_SIGNER = "5SIMULATEDtestColdkeyAddrZZZZZZZZZZZZZZZZZZZZZZZZ"
SIM_NEW_KEY = "5SIMULATEDnewColdkeyAddrZZZZZZZZZZZZZZZZZZZZZZZZZZ"
SIM_LABEL = "SIMULATED Owner (test)"


class Command(BaseCommand):
    help = "Simulate a coldkey-swap event and route via SubnetWebhook rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "--netuids",
            default="11,12,13",
            help="Comma-separated netuids to route to (default: 11,12,13).",
        )
        parser.add_argument(
            "--event",
            default="swap_coldkey_announced",
            choices=[
                "announce_coldkey_swap",
                "swap_coldkey_announced",
                "dispute_coldkey_swap",
                "reset_coldkey_swap",
                "clear_coldkey_swap_announcement",
            ],
            help="Coldkey lifecycle action to simulate (default: swap_coldkey_announced).",
        )
        parser.add_argument(
            "--block",
            type=int,
            default=9_999_999,
            help="Synthetic block number for the message (default: 9999999).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print which URLs would be hit; do not POST to Discord.",
        )

    def handle(self, *args, **opts):
        netuids = [int(x) for x in opts["netuids"].split(",") if x.strip()]
        event = opts["event"]
        block_number = opts["block"]
        dry_run = opts["dry_run"]

        targets = list(
            SubnetWebhook.objects.filter(netuid__in=netuids, enabled=True)
            .order_by("netuid", "id")
            .values_list("netuid", "url")
        )
        if not targets:
            raise CommandError(
                f"No enabled SubnetWebhook rows for {netuids}. Insert rows first."
            )

        self.stdout.write(self.style.MIGRATE_HEADING("Routing targets:"))
        for netuid, url in targets:
            self.stdout.write(f"  netuid={netuid}  {url[:60]}...")

        if dry_run:
            self.stdout.write(self.style.WARNING("\n--dry-run: skipping POST."))
            return

        _, created = Coldkey.objects.get_or_create(
            coldkey=SIM_SIGNER, defaults={"label": SIM_LABEL}
        )
        self.stdout.write(
            f"Coldkey row for signer: {'created' if created else 'already present'} "
            f"(label resolution will return {SIM_LABEL!r})"
        )

        sim_roles = ColdkeyRoles(owned_subnets=list(netuids))

        handler = ColdkeySwapNotification()
        enriched = [
            {
                "call_module": "SubtensorModule",
                "call_function": event,
                "address": SIM_SIGNER,
                "extrinsic_hash": f"0xsimulated{netuid:04d}",
                "extrinsic_index": 0,
                "success": True,
                "call_args": [
                    {"name": "old_coldkey", "value": SIM_SIGNER},
                    {"name": "new_coldkey", "value": SIM_NEW_KEY},
                ],
                "netuid": netuid,
                "_coldkey_roles": sim_roles,
            }
            for netuid in netuids
        ]

        sent = SubnetRoutedNotification.notify(handler, block_number, enriched)
        self.stdout.write(
            self.style.SUCCESS(f"\nDone. Routed extrinsic count: {sent}")
        )
