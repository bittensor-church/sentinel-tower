"""Prune data past the retention windows (see project.core.retention).

Two windows: ``--days`` (snapshot window) governs non-validator neuron
snapshots + their mechanism metrics; ``--bulk-days`` governs the bulk tables
(weight, bond, collateral, extrinsics). Used for the initial backlog purge
(run via the ``prune-retention`` compose profile service) and for ad-hoc
runs; the daily steady-state runs happen via the ``cleanup_expired_data``
Celery beat task, which shares the same advisory lock so the two can't
overlap.
"""

from django.core.management.base import BaseCommand

from project.core import retention


class Command(BaseCommand):
    help = "Delete rows older than the per-table retention windows; validator APY data is kept forever."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Snapshot retention window (default: settings.DATA_RETENTION_DAYS)",
        )
        parser.add_argument(
            "--bulk-days",
            type=int,
            default=None,
            help="Bulk-table (weight/bond/collateral/extrinsics) retention window "
            "(default: settings.DATA_RETENTION_BULK_DAYS)",
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
        try:
            result = retention.run(
                days=options["days"],
                bulk_days=options["bulk_days"],
                batch_size=options["batch_size"],
                dry_run=options["dry_run"],
                max_batches=options["max_batches"],
            )
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Interrupted — committed batches are kept; re-run to resume."))
            return
        # Deliberately exit 0 on lock-skip: another active run means the work
        # is happening, not a failure. Operators chaining the one-shot should
        # check the output, not the exit code.
        if result.get("skipped") == "lock":
            self.stdout.write(self.style.WARNING("Another retention run is in progress; nothing done."))
            return
        if result["cutoff_block"] is None and result["bulk_cutoff_block"] is None:
            self.stdout.write(self.style.SUCCESS("Nothing older than either retention window."))
            return

        verb = "Would delete" if options["dry_run"] else "Deleted"
        self.stdout.write(self.style.SUCCESS(f"Snapshot cutoff block: {result['cutoff_block']}"))
        self.stdout.write(self.style.SUCCESS(f"Bulk cutoff block: {result['bulk_cutoff_block']}"))
        for table, count in result["deleted"].items():
            self.stdout.write(f"  {verb} {table}: {count}")
