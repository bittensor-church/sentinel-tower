"""Management command to re-sync blockchain events from JSONL to database."""

from django.core.management.base import BaseCommand, CommandParser

from project.core.models import HyperparamEvent, IngestionCheckpoint, SetWeightsEvent
from project.dagster.jobs import HYPERPARAMS_FILE, SET_WEIGHTS_DIR


class Command(BaseCommand):
    help = "Re-sync blockchain events from JSONL files to database"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--type",
            choices=["all", "hyperparams", "set_weights"],
            default="all",
            help="Type of events to re-sync (default: all)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options) -> None:
        event_type = options["type"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        if event_type in ("all", "hyperparams"):
            self._resync_hyperparams(dry_run)

        if event_type in ("all", "set_weights"):
            self._resync_set_weights(dry_run)

        self.stdout.write(self.style.SUCCESS("Re-sync complete. Run the Dagster job to ingest records."))

    def _resync_hyperparams(self, dry_run: bool) -> None:
        event_count = HyperparamEvent.objects.count()
        self.stdout.write(f"Found {event_count} HyperparamEvent records to delete")

        if not dry_run:
            HyperparamEvent.objects.all().delete()
            IngestionCheckpoint.objects.filter(file_path=HYPERPARAMS_FILE).delete()
            self.stdout.write(self.style.SUCCESS("Deleted HyperparamEvent records and reset checkpoint"))

    def _resync_set_weights(self, dry_run: bool) -> None:
        event_count = SetWeightsEvent.objects.count()
        self.stdout.write(f"Found {event_count} SetWeightsEvent records to delete")

        if not dry_run:
            SetWeightsEvent.objects.all().delete()
            IngestionCheckpoint.objects.filter(file_path=SET_WEIGHTS_DIR).delete()
            self.stdout.write(self.style.SUCCESS("Deleted SetWeightsEvent records and reset checkpoint"))
