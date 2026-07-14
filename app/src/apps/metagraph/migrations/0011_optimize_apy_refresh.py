"""Speed up & harden the validator-APY materialized-view refreshes.

1. Partial index `metagraph_neuron_snapshot (block_id) WHERE is_validator`.
   Both APY views aggregate validator snapshots over a block-timestamp window;
   without this the planner Parallel-Seq-Scans the whole 45 GB table to apply the
   `is_validator` filter. Built CONCURRENTLY so it doesn't lock the table on prod.

2. Recreate `mv_subnet_validator_apy_epochs` with an overflow-guarded APY formula.
   A validator with dust `alpha_stake` but real `alpha_dividends` makes
   `(1 + alpha_dividends/alpha_stake) ^ (2629800/(tempo+1))` blow past `numeric`'s
   limit; one such row raised NumericValueOutOfRange and aborted the entire
   REFRESH, leaving the view permanently empty. Postgres evaluates `power(b, e)`
   as `exp(e * ln(b))`, so clamping the *base* doesn't help — `exp()` still
   overflows on a huge argument. Instead we compute APY as `exp(LEAST(e*ln(1+r),
   14))`: identical to `power()` for real values, but `exp()` never sees an
   argument large enough to overflow, and the result is then capped at 1e6 %.
"""

from django.db import migrations

# fmt: off
EPOCHS_VIEW_GUARDED = (
    "DROP MATERIALIZED VIEW IF EXISTS mv_subnet_validator_apy_epochs;",
    # Big one-time build of ~90 days of validator snapshots; default 4 MB work_mem
    # would spill to disk. Raised for this (autocommit) migration session only.
    "SET work_mem = '256MB';",
    """
    CREATE MATERIALIZED VIEW mv_subnet_validator_apy_epochs AS
    SELECT
        n.subnet_id,
        ns.neuron_id,
        h.hotkey,
        COALESCE(NULLIF(h.label, ''), LEFT(h.hotkey, 8) || '...') AS validator_name,
        b.number    AS epoch_block,
        b.timestamp AS epoch_ts,
        ns.alpha_dividends,
        ns.alpha_stake,
        COALESCE(NULLIF(s.tempo, 0), 360) AS tempo,
        LEAST(
            (exp(LEAST(
                (2629800.0 / (COALESCE(NULLIF(s.tempo, 0), 360) + 1))
                * ln(1 + ns.alpha_dividends::numeric / ns.alpha_stake::numeric),
                14::numeric
            )) - 1) * 100,
            1000000::numeric
        ) AS apy_pct
    FROM metagraph_neuron_snapshot ns
    JOIN metagraph_neuron n ON n.id     = ns.neuron_id
    JOIN metagraph_subnet s ON s.netuid = n.subnet_id
    JOIN metagraph_hotkey h ON h.id     = n.hotkey_id
    JOIN metagraph_block  b ON b.number = ns.block_id
    JOIN metagraph_dump   d ON d.block_id = ns.block_id AND d.netuid = n.subnet_id
    WHERE ns.is_validator = true
      AND ns.alpha_stake > 0
      AND ns.alpha_dividends > 0
      AND d.epoch_position = 2
      AND b.timestamp >= NOW() - INTERVAL '90 days';
    """,
    "CREATE UNIQUE INDEX idx_mv_subnet_validator_apy_epochs_pk "
    "ON mv_subnet_validator_apy_epochs (subnet_id, neuron_id, epoch_block);",
    "CREATE INDEX idx_mv_subnet_validator_apy_epochs_subnet_ts "
    "ON mv_subnet_validator_apy_epochs (subnet_id, epoch_ts);",
)

# Reverse: restore the original (unguarded) view from migration 0010.
EPOCHS_VIEW_ORIGINAL = (
    "DROP MATERIALIZED VIEW IF EXISTS mv_subnet_validator_apy_epochs;",
    """
    CREATE MATERIALIZED VIEW mv_subnet_validator_apy_epochs AS
    SELECT
        n.subnet_id,
        ns.neuron_id,
        h.hotkey,
        COALESCE(NULLIF(h.label, ''), LEFT(h.hotkey, 8) || '...') AS validator_name,
        b.number    AS epoch_block,
        b.timestamp AS epoch_ts,
        ns.alpha_dividends,
        ns.alpha_stake,
        COALESCE(NULLIF(s.tempo, 0), 360) AS tempo,
        (power(
            1 + ns.alpha_dividends::numeric / ns.alpha_stake::numeric,
            2629800.0 / (COALESCE(NULLIF(s.tempo, 0), 360) + 1)
         ) - 1) * 100 AS apy_pct
    FROM metagraph_neuron_snapshot ns
    JOIN metagraph_neuron n ON n.id     = ns.neuron_id
    JOIN metagraph_subnet s ON s.netuid = n.subnet_id
    JOIN metagraph_hotkey h ON h.id     = n.hotkey_id
    JOIN metagraph_block  b ON b.number = ns.block_id
    JOIN metagraph_dump   d ON d.block_id = ns.block_id AND d.netuid = n.subnet_id
    WHERE ns.is_validator = true
      AND ns.alpha_stake > 0
      AND ns.alpha_dividends > 0
      AND d.epoch_position = 2
      AND b.timestamp >= NOW() - INTERVAL '90 days';
    """,
    "CREATE UNIQUE INDEX idx_mv_subnet_validator_apy_epochs_pk "
    "ON mv_subnet_validator_apy_epochs (subnet_id, neuron_id, epoch_block);",
    "CREATE INDEX idx_mv_subnet_validator_apy_epochs_subnet_ts "
    "ON mv_subnet_validator_apy_epochs (subnet_id, epoch_ts);",
)
# fmt: on


class Migration(migrations.Migration):
    # CREATE INDEX CONCURRENTLY and CREATE MATERIALIZED VIEW WITH DATA must not run
    # inside the migration's transaction.
    atomic = False

    dependencies = [
        ("metagraph", "0010_create_subnet_validator_apy_epochs_view"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ns_validator_block "
                "ON metagraph_neuron_snapshot (block_id) WHERE is_validator;"
            ),
            reverse_sql="DROP INDEX IF EXISTS idx_ns_validator_block;",
        ),
        migrations.RunSQL(sql=EPOCHS_VIEW_GUARDED, reverse_sql=EPOCHS_VIEW_ORIGINAL),
    ]
