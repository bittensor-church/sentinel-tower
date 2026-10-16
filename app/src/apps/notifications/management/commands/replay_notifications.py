"""Replay the notification pipeline for past blocks without posting anything.

Fetches each block from the chain, runs the same parsing, unwrapping and
handler matching as ingestion, and prints every notification payload with
its target channel. No webhook is called and nothing is written to the
database (the run is wrapped in a rolled-back transaction, and hyperparam
enrichment is read-only).

Usage (inside docker):
    docker compose run --rm app python manage.py replay_notifications 9155226 9155237
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from sentinel.v1.dto import EventDTO, ExtrinsicDTO
from sentinel.v1.providers.base import BlockchainProvider
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from apps.extrinsics.block_tasks import block_level_events, parse_extrinsic
from apps.extrinsics.hyperparam_service import enrich_extrinsics_with_previous_values
from apps.notifications import dispatch_block_event_notifications, dispatch_block_notifications
from apps.notifications.channels import DryRunDelivery, dry_run
from project.core.utils import get_archive_provider


@dataclass(frozen=True)
class _Block:
    extrinsics: list[ExtrinsicDTO]
    events: list[EventDTO]
    timestamp: int | None

    @classmethod
    def ingest(cls, provider: BlockchainProvider, block_number: int) -> _Block:
        """Read everything the replay needs while the provider is open (the block loads lazily)."""
        block = sentinel_service(provider).ingest_block(block_number)
        if not block.extrinsics:
            raise ValueError("no extrinsics returned")
        return cls(extrinsics=block.extrinsics, events=block.events or [], timestamp=block.timestamp)


class Command(BaseCommand):
    help = "Dry-run the notification pipeline for the given blocks and print the payloads instead of posting them."

    def add_arguments(self, parser) -> None:
        parser.add_argument("blocks", nargs="+", type=int, help="Block numbers to replay.")
        parser.add_argument(
            "--archive",
            action="store_true",
            help="Read from the archive node directly (default: live node, archive if the block is unavailable).",
        )

    def handle(self, *args, **opts) -> None:
        for block_number in opts["blocks"]:
            block = self._read(block_number, force_archive=opts["archive"])
            deliveries = self._replay(block_number, block)
            self._report(block_number, len(block.extrinsics), deliveries)

    def _read(self, block_number: int, *, force_archive: bool) -> _Block:
        if not force_archive:
            try:
                with bittensor_provider() as live:
                    return _Block.ingest(live, block_number)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"Block {block_number}: live node failed ({e}); trying archive")
        try:
            with get_archive_provider() as archive:
                return _Block.ingest(archive, block_number)
        except Exception as e:
            raise CommandError(f"Block {block_number} could not be read from the chain: {e}") from e

    @staticmethod
    def _replay(block_number: int, block: _Block) -> list[DryRunDelivery]:
        with transaction.atomic(), dry_run() as deliveries:
            parsed = [
                p for e in block.extrinsics if (p := parse_extrinsic(e, block_number, block.timestamp)) is not None
            ]
            dispatch_block_notifications(block_number, enrich_extrinsics_with_previous_values(parsed, persist=False))
            if events := block_level_events(block.events):
                dispatch_block_event_notifications(block_number, events)
            transaction.set_rollback(True)
        return deliveries

    def _report(self, block_number: int, extrinsic_count: int, deliveries: list[DryRunDelivery]) -> None:
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Block {block_number}: {extrinsic_count} extrinsics, {len(deliveries)} notification(s) — dry run, nothing posted"
            )
        )
        for delivery in deliveries:
            configured = (
                f"{delivery.url_count} webhook(s) configured" if delivery.url_count else "no webhook configured"
            )
            self.stdout.write(f"\n→ {delivery.channel} ({configured})")
            self.stdout.write(delivery.payload.get("content", str(delivery.payload)))
        self.stdout.write("")
