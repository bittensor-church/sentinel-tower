"""Management command to re-sync blockchain events from JSONL to database."""

from django.core.management.base import BaseCommand, CommandParser

from apps.extrinsics.models import Extrinsic
from project.core.models import IngestionCheckpoint


class Command(BaseCommand):
    help = "Re-sync blockchain events from JSONL files to database"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        self._resync_extrinsics(dry_run)

        self.stdout.write(self.style.SUCCESS("Re-sync complete. Run the Dagster job to ingest records."))

    def _resync_extrinsics(self, dry_run: bool) -> None:
        event_count = Extrinsic.objects.count()
        self.stdout.write(f"Found {event_count} Extrinsic records to delete")

        if not dry_run:
            Extrinsic.objects.all().delete()
            IngestionCheckpoint.objects.all().delete()
            self.stdout.write(self.style.SUCCESS("Deleted Extrinsic records and reset checkpoints"))
