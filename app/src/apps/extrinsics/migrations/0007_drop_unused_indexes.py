"""Drop unused indexes on the extrinsics table.

Identified via pg_stat_user_indexes (idx_scan = 0) on prod; reclaims
~5 GB. All drops run CONCURRENTLY and use IF EXISTS, so the migration
is idempotent and safe to run even if some indexes were already dropped
manually on prod.

The extrinsic_hash column stays UNIQUE — only its redundant
varchar_pattern_ops (_like) index is dropped.
"""

from django.db import migrations, models


def _drop_meta_index(model_name, index_name, create_sql):
    """State removes the index; DB drops it concurrently if present."""
    return migrations.SeparateDatabaseAndState(
        state_operations=[
            migrations.RemoveIndex(model_name=model_name, name=index_name),
        ],
        database_operations=[
            migrations.RunSQL(
                sql=f"DROP INDEX CONCURRENTLY IF EXISTS {index_name};",
                reverse_sql=create_sql,
            ),
        ],
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("extrinsics", "0006_rename_extrinsics_created_f0a498_idx_extrinsics_created_c6a814_idx_and_more"),
    ]

    operations = [
        _drop_meta_index(
            "extrinsic",
            "extrinsics_block_h_7ae207_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_block_h_7ae207_idx ON extrinsics (block_hash);",
        ),
        _drop_meta_index(
            "extrinsic",
            "extrinsics_address_653e67_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_address_653e67_idx "
            "ON extrinsics (address, block_number);",
        ),
        _drop_meta_index(
            "extrinsic",
            "extrinsics_call_mo_837e16_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_call_mo_837e16_idx "
            "ON extrinsics (call_module, call_function, success);",
        ),
        _drop_meta_index(
            "extrinsic",
            "extrinsics_netuid_056ebb_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_netuid_056ebb_idx "
            "ON extrinsics (netuid, call_function);",
        ),
        _drop_meta_index(
            "extrinsic",
            "extrinsics_created_c6a814_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_created_c6a814_idx ON extrinsics (created_at);",
        ),
        _drop_meta_index(
            "extrinsic",
            "extrinsics_call_fu_dba940_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_call_fu_dba940_idx "
            "ON extrinsics (call_function, block_timestamp);",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="extrinsic",
                    name="block_hash",
                    field=models.CharField(blank=True, max_length=66),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="block_timestamp",
                    field=models.PositiveBigIntegerField(
                        blank=True,
                        help_text="Block timestamp from Timestamp.Now",
                        null=True,
                    ),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="call_function",
                    field=models.CharField(max_length=100),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="address",
                    field=models.CharField(blank=True, max_length=66),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="success",
                    field=models.BooleanField(default=False),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="netuid",
                    field=models.PositiveIntegerField(blank=True, null=True),
                ),
                migrations.AlterField(
                    model_name="extrinsic",
                    name="created_at",
                    field=models.DateTimeField(auto_now_add=True),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_block_hash_41ffbd7c;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_block_hash_41ffbd7c ON extrinsics (block_hash);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_block_hash_41ffbd7c_like;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_block_hash_41ffbd7c_like "
                        "ON extrinsics (block_hash varchar_pattern_ops);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_block_timestamp_0967e973;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_block_timestamp_0967e973 "
                        "ON extrinsics (block_timestamp);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_call_function_a5f205a9;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_call_function_a5f205a9 "
                        "ON extrinsics (call_function);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_call_function_a5f205a9_like;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_call_function_a5f205a9_like "
                        "ON extrinsics (call_function varchar_pattern_ops);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_address_96ac996e;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_address_96ac996e ON extrinsics (address);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_address_96ac996e_like;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_address_96ac996e_like "
                        "ON extrinsics (address varchar_pattern_ops);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_success_466a04cf;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_success_466a04cf ON extrinsics (success);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_netuid_5cae5805;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS extrinsics_netuid_5cae5805 ON extrinsics (netuid);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_created_at_8d852993;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "extrinsics_created_at_8d852993 ON extrinsics (created_at);"
                    ),
                ),
            ],
        ),
        migrations.RunSQL(
            sql="DROP INDEX CONCURRENTLY IF EXISTS extrinsics_extrinsic_hash_6b398364_like;",
            reverse_sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "extrinsics_extrinsic_hash_6b398364_like "
                "ON extrinsics (extrinsic_hash varchar_pattern_ops);"
            ),
        ),
    ]
