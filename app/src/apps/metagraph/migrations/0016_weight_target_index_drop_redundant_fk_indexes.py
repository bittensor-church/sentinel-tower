"""Incoming-weight covering index, and drop two redundant FK auto-indexes.

1. Add `idx_weight_target_mech_block` on
   `metagraph_weight (target_neuron_id, mech_id, block_id)
    INCLUDE (source_neuron_id, weight)`.

   Dashboard panels that chart "the weights one miner received over a time
   window" filter on `target_neuron_id`, which no index covered:
   `unique_weight` leads with `source_neuron_id`, and `idx_weight_block`
   only narrows by block. A 7-day panel therefore fell back to a parallel
   seq scan of the whole 137M-row / 11.4 GB table (~66s of read I/O), and
   the resulting 5-row estimate also drove the planner into a 643M-iteration
   nested loop against `metagraph_hotkey`. Measured on prod: 136s.

   Column order is deliberate — the two equality predicates first and the
   block range last, so all three become index conditions rather than post-
   scan filters. `mech_id` is a key column (not INCLUDE) so it can be an
   index condition; it is always 0 today but the schema allows more.
   The INCLUDE payload carries the two remaining columns the panels select,
   making the scan index-only: a 30-day window currently costs ~14k random
   heap reads (~57s of the 67s runtime) that this eliminates.

2. Drop `metagraph_neuron_snapshot_neuron_id_75a757dc` (1.9 GB) and
   `metagraph_mechanism_metrics_snapshot_id_d4dc12fb` (5.8 GB).

   Both are Django FK auto-indexes on a column that is already the leading
   column of a unique constraint — `unique_neuron_block (neuron_id,
   block_id)` and `unique_snapshot_mech (snapshot_id, mech_id)` — so every
   lookup and every FK cascade check they serve is served by the unique
   index instead. They only cost disk and write amplification, which matters
   here: these are the two highest-churn tables (219M and 235M rows) on a
   host with 7.7 GB RAM against a ~160 GB dataset, so index pages evicted
   for no query benefit are pages the page cache cannot spend on hot data.

   Dropped via SeparateDatabaseAndState (matching migration 0007) because
   FK auto-indexes are not state-tracked `models.Index` objects: the state
   side is the `db_index=False` AlterField, the database side is a
   concurrent drop.

Everything runs CONCURRENTLY so none of it takes a lock the ingestion
pipeline would queue behind. The two drops are additionally guarded with
IF EXISTS and so are idempotent; the create is not (Django emits a plain
CREATE INDEX CONCURRENTLY), so if it is ever interrupted, drop the
resulting INVALID index before re-running:

    SELECT indexrelid::regclass FROM pg_index WHERE NOT indexisvalid;
    DROP INDEX CONCURRENTLY idx_weight_target_mech_block;
"""

from django.contrib.postgres.operations import AddIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE/DROP INDEX CONCURRENTLY must not run inside a transaction.
    atomic = False

    dependencies = [
        ("metagraph", "0015_validator_apy_epoch"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="weight",
            index=models.Index(
                fields=["target_neuron", "mech_id", "block"],
                include=["source_neuron", "weight"],
                name="idx_weight_target_mech_block",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="neuronsnapshot",
                    name="neuron",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="snapshots",
                        to="metagraph.neuron",
                    ),
                ),
                migrations.AlterField(
                    model_name="mechanismmetrics",
                    name="snapshot",
                    field=models.ForeignKey(
                        db_index=False,
                        on_delete=models.deletion.CASCADE,
                        related_name="mechanism_metrics",
                        to="metagraph.neuronsnapshot",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=("DROP INDEX CONCURRENTLY IF EXISTS metagraph_neuron_snapshot_neuron_id_75a757dc;"),
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_neuron_snapshot_neuron_id_75a757dc "
                        "ON metagraph_neuron_snapshot (neuron_id);"
                    ),
                ),
                migrations.RunSQL(
                    sql=("DROP INDEX CONCURRENTLY IF EXISTS metagraph_mechanism_metrics_snapshot_id_d4dc12fb;"),
                    reverse_sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "metagraph_mechanism_metrics_snapshot_id_d4dc12fb "
                        "ON metagraph_mechanism_metrics (snapshot_id);"
                    ),
                ),
            ],
        ),
    ]
