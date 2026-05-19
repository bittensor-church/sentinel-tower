"""Manually refresh mv_validator_apy_windows.

Same operation Celery beat runs every 15 minutes — useful for ad-hoc refreshes
after backfills or for testing. Pass --no-concurrent for the first refresh on
a freshly migrated DB if CONCURRENTLY fails (PostgreSQL allows it on empty
MVs, but if anything has gone wrong with the unique index, the non-concurrent
form is the safe fallback).
"""

import structlog
from django.core.management.base import BaseCommand
from django.db import connection

logger = structlog.get_logger()


class Command(BaseCommand):
    help = "Refresh the mv_validator_apy_windows materialized view."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-concurrent",
            action="store_true",
            help="Use plain REFRESH (locks reads). Default is REFRESH CONCURRENTLY.",
        )

    def handle(self, *args, **options) -> None:
        sql = (
            "REFRESH MATERIALIZED VIEW mv_validator_apy_windows;"
            if options["no_concurrent"]
            else "REFRESH MATERIALIZED VIEW CONCURRENTLY mv_validator_apy_windows;"
        )
        self.stdout.write(f"Running: {sql}")
        with connection.cursor() as cursor:
            cursor.execute(sql)
        self.stdout.write(self.style.SUCCESS("Refresh complete."))
