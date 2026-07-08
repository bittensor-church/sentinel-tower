"""Prune data past the retention window (see project.core.retention).

Used for the initial backlog purge (run via the ``prune-retention`` compose
profile service) and for ad-hoc runs; the daily steady-state runs happen via
the ``cleanup_expired_data`` Celery beat task, which shares the same advisory
lock so the two can't overlap.
"""

from django.core.management.base import BaseCommand

from project.core import retention


class Command(BaseCommand):
    help = "Delete rows older than the retention window; validator APY data is kept forever."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Retention window (default: settings.DATA_RETENTION_DAYS)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=None,
            help="Rows per delete batch (default: settings.DATA_RETENTION_BATCH_SIZE)",
        )
        parser.add_argument(
            "--max-batches",
            type=int,
            default=None,
            help="Stop after N batches per table (resumable; default: unlimited)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report per-table counts without deleting",
        )

    def handle(self, *args, **options) -> None:
        result = retention.run(
            days=options["days"],
            batch_size=options["batch_size"],
            dry_run=options["dry_run"],
            max_batches=options["max_batches"],
        )
        if result.get("skipped") == "lock":
            self.stdout.write(self.style.WARNING("Another retention run is in progress; nothing done."))
            return
        if result["cutoff_block"] is None:
            self.stdout.write(self.style.SUCCESS("Nothing older than the retention window."))
            return

        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(self.style.SUCCESS(f"Cutoff block: {result['cutoff_block']}"))
        for table, count in result["deleted"].items():
            self.stdout.write(f"  {verb} {table}: {count}")
