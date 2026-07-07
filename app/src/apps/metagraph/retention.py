"""Retention pruning for the metagraph app.

Deletes rows whose block is at or below a cutoff block number, in bounded
batches (each batch is its own transaction, with a short sleep in between so
autovacuum and live sync keep up). Validator neuron snapshots and their
mechanism metrics are never deleted — the APY materialized views read them.

There are no DB-level cascades (all FKs are NO ACTION, DEFERRABLE INITIALLY
DEFERRED), so each snapshot batch deletes child mechanism_metrics rows and
the snapshots in one data-modifying CTE statement; the deferred FK check
passes at COMMIT.
"""

import time

import structlog
from django.conf import settings
from django.db import connection, transaction

logger = structlog.get_logger()

# Tables prunable by a simple indexed block-column range delete.
_SIMPLE_TABLES = (
    ("metagraph_weight", "block_id"),
    ("metagraph_bond", "block_id"),
    ("metagraph_collateral", "block_id"),
)

_SNAPSHOT_BATCH_DELETE_SQL = """
    WITH batch AS (
        SELECT id FROM metagraph_neuron_snapshot
        WHERE block_id <= %(cutoff)s AND is_validator = false
        ORDER BY block_id
        LIMIT %(batch_size)s
    ),
    mm AS (
        DELETE FROM metagraph_mechanism_metrics
        WHERE snapshot_id IN (SELECT id FROM batch)
        RETURNING 1
    ),
    ns AS (
        DELETE FROM metagraph_neuron_snapshot
        WHERE id IN (SELECT id FROM batch)
        RETURNING 1
    )
    SELECT (SELECT count(*) FROM mm) AS mm_deleted, (SELECT count(*) FROM ns) AS ns_deleted
"""


def _delete_snapshot_batch(cutoff_block: int, batch_size: int) -> tuple[int, int]:
    """Delete one batch of non-validator snapshots and their mechanism metrics.

    Returns (mechanism_metrics_deleted, snapshots_deleted).
    """
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            _SNAPSHOT_BATCH_DELETE_SQL,
            {"cutoff": cutoff_block, "batch_size": batch_size},
        )
        mm_deleted, ns_deleted = cursor.fetchone()
        return mm_deleted, ns_deleted


def _delete_simple_batch(table: str, block_column: str, cutoff_block: int, batch_size: int) -> int:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            f"DELETE FROM {table} WHERE id IN ("  # noqa: S608 — table names are module constants
            f" SELECT id FROM {table} WHERE {block_column} <= %(cutoff)s"
            f" ORDER BY {block_column} LIMIT %(batch_size)s)",
            {"cutoff": cutoff_block, "batch_size": batch_size},
        )
        return cursor.rowcount


def _count(sql: str, params: dict) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()[0]


def prune_expired(
    cutoff_block: int,
    batch_size: int | None = None,
    dry_run: bool = False,
    max_batches: int | None = None,
) -> dict[str, int]:
    """Prune metagraph rows at or below ``cutoff_block``. Returns rows per table."""
    batch_size = batch_size or settings.RETENTION_DELETE_BATCH_SIZE
    params = {"cutoff": cutoff_block, "batch_size": batch_size}

    if dry_run:
        return {
            "metagraph_neuron_snapshot": _count(
                "SELECT count(*) FROM metagraph_neuron_snapshot WHERE block_id <= %(cutoff)s AND is_validator = false",
                params,
            ),
            "metagraph_mechanism_metrics": _count(
                "SELECT count(*) FROM metagraph_mechanism_metrics mm"
                " JOIN metagraph_neuron_snapshot ns ON ns.id = mm.snapshot_id"
                " WHERE ns.block_id <= %(cutoff)s AND ns.is_validator = false",
                params,
            ),
            **{
                table: _count(
                    f"SELECT count(*) FROM {table} WHERE {col} <= %(cutoff)s",  # noqa: S608
                    params,
                )
                for table, col in _SIMPLE_TABLES
            },
        }

    deleted = {
        "metagraph_neuron_snapshot": 0,
        "metagraph_mechanism_metrics": 0,
        **{table: 0 for table, _ in _SIMPLE_TABLES},
    }

    batches = 0
    while max_batches is None or batches < max_batches:
        mm_count, ns_count = _delete_snapshot_batch(cutoff_block, batch_size)
        deleted["metagraph_mechanism_metrics"] += mm_count
        deleted["metagraph_neuron_snapshot"] += ns_count
        batches += 1
        if ns_count == 0:
            break
        logger.info("retention batch", table="metagraph_neuron_snapshot", deleted=ns_count)
        time.sleep(settings.RETENTION_BATCH_SLEEP_SECONDS)

    for table, col in _SIMPLE_TABLES:
        batches = 0
        while max_batches is None or batches < max_batches:
            count = _delete_simple_batch(table, col, cutoff_block, batch_size)
            deleted[table] += count
            batches += 1
            if count == 0:
                break
            logger.info("retention batch", table=table, deleted=count)
            time.sleep(settings.RETENTION_BATCH_SLEEP_SECONDS)

    return deleted
