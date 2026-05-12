"""Add composite btree indexes on (call_function, block_timestamp) and (call_module, block_timestamp).

Grafana dashboards filter extrinsics by call_function or call_module within a time window
(e.g. "registrations in the last 7 days", "Sudo calls this month"). Without an index leading
on the equality column those queries fall back to seq scans on the ~21M-row extrinsics table
and time out at the client's 60s limit.

Each composite covers a whole family of dashboard panels:
- (call_function, block_timestamp): register_network, dissolve_network, coldkey swaps, etc.
- (call_module, block_timestamp): Sudo, AdminUtils, etc.

`success = true` is intentionally NOT in the index - left as a heap filter on top of the
narrow index scan. Most rows have success=true so it would inflate the index without speeding
the rare success=false queries that matter.

Built CONCURRENTLY (atomic = False) to avoid taking an exclusive lock on the table during
deploy. `IF NOT EXISTS` makes the migration safe to run on a host where the index was
already created manually for emergency use.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("extrinsics", "0010_seed_all_subtensor_error_codes"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="extrinsic",
                    index=models.Index(
                        fields=["call_function", "block_timestamp"],
                        name="extrinsics_call_function_ts",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_call_function_ts "
                        "ON extrinsics (call_function, block_timestamp);"
                    ),
                    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_call_function_ts;",
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddIndex(
                    model_name="extrinsic",
                    index=models.Index(
                        fields=["call_module", "block_timestamp"],
                        name="extrinsics_call_module_ts",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_call_module_ts "
                        "ON extrinsics (call_module, block_timestamp);"
                    ),
                    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_call_module_ts;",
                ),
            ],
        ),
    ]
