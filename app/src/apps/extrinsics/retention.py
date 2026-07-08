"""Retention pruning for the extrinsics app.

Deletes extrinsics whose block is at or below a cutoff block number, in
bounded batches (each batch is its own transaction, with a short sleep in
between so autovacuum and live sync keep up). The ``extrinsics`` table has no
foreign keys, so a plain indexed range delete on ``block_number`` suffices;
the block numbers are on the same chain as the metagraph blocks, so the same
integer cutoff applies to both apps.

Do not run concurrently with a historical backfill that inserts extrinsics
below the cutoff.
"""

import time

import structlog
from django.conf import settings
from django.db import connection, transaction

logger = structlog.get_logger()

_TABLE = "extrinsics"

_BATCH_DELETE_SQL = """
    DELETE FROM extrinsics WHERE id IN (
        SELECT id FROM extrinsics WHERE block_number <= %(cutoff)s
        ORDER BY block_number LIMIT %(batch_size)s)
"""


def _delete_batch(cutoff_block: int, batch_size: int) -> int:
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(_BATCH_DELETE_SQL, {"cutoff": cutoff_block, "batch_size": batch_size})
        return cursor.rowcount


def _count(cutoff_block: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM extrinsics WHERE block_number <= %(cutoff)s",
            {"cutoff": cutoff_block},
        )
        return cursor.fetchone()[0]


def prune_expired(
    cutoff_block: int,
    batch_size: int | None = None,
    dry_run: bool = False,
    max_batches: int | None = None,
) -> dict[str, int]:
    """Prune extrinsics at or below ``cutoff_block``. Returns rows per table.

    ``max_batches`` caps the number of batches and makes runs resumable — a
    capped run deletes the oldest rows first, and the next run picks up where
    it left off.

    ``dry_run=True`` returns would-delete counts without deleting anything and
    ignores ``max_batches``.

    Single-flight/serialization is the caller's job — the
    ``project.core.retention`` orchestrator wraps this in a Postgres advisory
    lock, so concurrent runs can't overlap; do not call this concurrently from
    elsewhere.
    """
    if batch_size is None:
        batch_size = settings.DATA_RETENTION_BATCH_SIZE
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")

    if dry_run:
        return {_TABLE: _count(cutoff_block)}

    logger.info("Retention prune starting", cutoff_block=cutoff_block, batch_size=batch_size)

    deleted = {_TABLE: 0}
    batches = 0
    while max_batches is None or batches < max_batches:
        count = _delete_batch(cutoff_block, batch_size)
        deleted[_TABLE] += count
        batches += 1
        if count == 0:
            break
        logger.info("Pruned retention batch", table=_TABLE, rows=count)
        time.sleep(settings.DATA_RETENTION_BATCH_SLEEP_SECONDS)

    logger.info("Retention prune finished", cutoff_block=cutoff_block, **deleted)
    return deleted
