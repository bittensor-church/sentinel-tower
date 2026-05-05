"""Add a BRIN index on extrinsics.block_timestamp.

The dashboard's $__timeFilter / BETWEEN clauses target block_timestamp,
but no index existed (the previous one was dropped in 0007). BRIN fits
this column perfectly: append-only, monotonic, multi-million rows -
the index is kilobytes and range scans are fast.

Built CONCURRENTLY to avoid taking an exclusive lock on the table.
"""

from django.contrib.postgres.indexes import BrinIndex
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("extrinsics", "0007_drop_unused_indexes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="extrinsic",
                    index=BrinIndex(fields=["block_timestamp"], name="extrinsics_block_ts_brin"),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_block_ts_brin "
                        "ON extrinsics USING BRIN (block_timestamp);"
                    ),
                    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_block_ts_brin;",
                ),
            ],
        ),
    ]
