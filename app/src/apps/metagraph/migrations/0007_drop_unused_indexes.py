"""Drop unused indexes on bond/weight/neuron_snapshot/mechanism_metrics.

Identified via pg_stat_user_indexes (idx_scan = 0) on prod; reclaims
~25 GB by dropping indexes that have never been used since stats reset.

All drops run CONCURRENTLY and use IF EXISTS, so the migration is
idempotent and safe to run even if some indexes were already dropped
manually on prod.
"""

from django.db import migrations, models


def _drop(model_name, index_name, create_sql):
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
        ("metagraph", "0006_drop_validator_weekly_apy_view"),
    ]

    operations = [
        _drop(
            "neuronsnapshot",
            "metagraph_n_total_s_065941_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_n_total_s_065941_idx "
            "ON metagraph_neuron_snapshot (total_stake DESC);",
        ),
        _drop(
            "neuronsnapshot",
            "metagraph_n_block_i_e0bb78_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_n_block_i_e0bb78_idx "
            "ON metagraph_neuron_snapshot (block_id);",
        ),
        _drop(
            "neuronsnapshot",
            "idx_validator_snapshots",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_validator_snapshots "
            "ON metagraph_neuron_snapshot (block_id, neuron_id) WHERE is_validator = TRUE;",
        ),
        _drop(
            "mechanismmetrics",
            "metagraph_m_snapsho_2f7d15_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_m_snapsho_2f7d15_idx "
            "ON metagraph_mechanism_metrics (snapshot_id);",
        ),
        _drop(
            "weight",
            "metagraph_w_block_i_210f72_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_w_block_i_210f72_idx "
            "ON metagraph_weight (block_id, target_neuron_id);",
        ),
        _drop(
            "weight",
            "metagraph_w_block_i_742f8c_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_w_block_i_742f8c_idx "
            "ON metagraph_weight (block_id, source_neuron_id);",
        ),
        _drop(
            "bond",
            "metagraph_b_block_i_667861_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_b_block_i_667861_idx "
            "ON metagraph_bond (block_id, target_neuron_id);",
        ),
        _drop(
            "bond",
            "metagraph_b_block_i_ac8e94_idx",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS metagraph_b_block_i_ac8e94_idx "
            "ON metagraph_bond (block_id, source_neuron_id);",
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="weight",
                    name="source_neuron",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="outgoing_weights",
                        to="metagraph.neuron",
                    ),
                ),
                migrations.AlterField(
                    model_name="weight",
                    name="target_neuron",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="incoming_weights",
                        to="metagraph.neuron",
                    ),
                ),
                migrations.AlterField(
                    model_name="weight",
                    name="block",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="weights",
                        to="metagraph.block",
                    ),
                ),
                migrations.AlterField(
                    model_name="bond",
                    name="source_neuron",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="outgoing_bonds",
                        to="metagraph.neuron",
                    ),
                ),
                migrations.AlterField(
                    model_name="bond",
                    name="target_neuron",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="incoming_bonds",
                        to="metagraph.neuron",
                    ),
                ),
                migrations.AlterField(
                    model_name="bond",
                    name="block",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="bonds",
                        to="metagraph.block",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_weight_source_neuron_id_60ee247f;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_weight_source_neuron_id_60ee247f "
                        "ON metagraph_weight (source_neuron_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_weight_target_neuron_id_b3f36c43;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_weight_target_neuron_id_b3f36c43 "
                        "ON metagraph_weight (target_neuron_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_weight_block_id_61a7f6d7;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_weight_block_id_61a7f6d7 "
                        "ON metagraph_weight (block_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_bond_source_neuron_id_1e2dea7d;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_bond_source_neuron_id_1e2dea7d "
                        "ON metagraph_bond (source_neuron_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_bond_target_neuron_id_609ad385;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_bond_target_neuron_id_609ad385 "
                        "ON metagraph_bond (target_neuron_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql="DROP INDEX CONCURRENTLY IF EXISTS metagraph_bond_block_id_8ba20c7d;",
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_bond_block_id_8ba20c7d "
                        "ON metagraph_bond (block_id);"
                    ),
                ),
            ],
        ),
    ]
