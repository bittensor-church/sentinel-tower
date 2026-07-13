"""Retention prune-scan index for neuron snapshots.

1. Partial index `metagraph_neuron_snapshot (block_id) WHERE NOT is_validator`.
   The retention prune deletes non-validator snapshots in batches ordered by
   block_id; with a full block_id index every batch's `ORDER BY block_id
   LIMIT n` walk restarts at the index left edge and re-scans the millions of
   forever-kept validator rows (plus dead entries) before reaching deletable
   ones — the initial backlog purge took ~26h largely because of this. The
   partial index contains only prunable rows, so each batch starts at the
   oldest deletable row. Built CONCURRENTLY so it doesn't lock the table.

2. Drop `idx_nsnapshot_block` (added by migration 0012 as a state-tracked
   AddIndex). It duplicates the Django FK auto-index on block_id
   (`metagraph_neuron_snapshot_block_id_96edc0ac`) — ~4-5 GB of prod disk for
   no additional query coverage. Dropped CONCURRENTLY via the state-tracked
   RemoveIndexConcurrently, matching how it was created.
"""

from django.contrib.postgres.operations import AddIndexConcurrently, RemoveIndexConcurrently
from django.db import migrations, models


class Migration(migrations.Migration):
    # CREATE/DROP INDEX CONCURRENTLY must not run inside a transaction.
    atomic = False

    dependencies = [
        ("metagraph", "0013_retention_block_indexes"),
    ]

    operations = [
        AddIndexConcurrently(
            model_name="neuronsnapshot",
            index=models.Index(
                fields=["block"],
                condition=models.Q(is_validator=False),
                name="idx_ns_miner_block",
            ),
        ),
        RemoveIndexConcurrently(
            model_name="neuronsnapshot",
            name="idx_nsnapshot_block",
        ),
    ]
