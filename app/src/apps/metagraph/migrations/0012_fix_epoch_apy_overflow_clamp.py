"""Properly bound the per-epoch APY formula so `power()` can't overflow.

Migration 0011 tried to guard `mv_subnet_validator_apy_epochs` by clamping the
per-epoch *ratio* (`alpha_dividends/alpha_stake`) to 1000 and capping the final
`apy_pct` with an outer `LEAST(..., 1e6)`. Both guards are insufficient: the
overflow happens *inside* `power(base, N)` before the outer `LEAST` ever runs,
and Postgres' `numeric` `exp()`/`power()` overflow around `exp(5934)` ≈ 10^2577
— far below `numeric`'s raw storage limit. With N = 2629800/(tempo+1) ≈ 7285 for
the standard tempo, the base must stay below ~1.0013; a ratio clamp of 1000
(base = 1001) overflows by thousands of orders of magnitude. So a single dust
`alpha_stake` validator still aborted the whole REFRESH.

The real bound is on the *base*, not the ratio. The APY cap is 1e6, and
`apy_pct = (power(base, N) - 1) * 100`, so the cap corresponds to
`power(base, N) = 10001`, i.e. `base = 10001^(1/N) = power(10001, (tempo+1)/2629800)`.
Clamping `1 + ratio` to that value keeps `power()` at most 10001 (no overflow)
and makes a clamped row land exactly on the 1e6 cap. The outer `LEAST(..., 1e6)`
is now mathematically redundant but kept as a defensive belt-and-suspenders cap.
"""

from django.db import migrations

# fmt: off
EPOCHS_VIEW_BASE_CLAMPED = [
    "DROP MATERIALIZED VIEW IF EXISTS mv_subnet_validator_apy_epochs;",
    # Big one-time rebuild of ~90 days of validator snapshots; default 4 MB
    # work_mem would spill to disk. Raised for this (autocommit) session only.
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
            (power(
                -- Clamp the base to the value that yields the 1e6 APY cap, so
                -- power() itself can never overflow numeric. 10001 = the power()
                -- result corresponding to apy_pct = 1e6 ((10001 - 1) * 100).
                LEAST(
                    1 + ns.alpha_dividends::numeric / ns.alpha_stake::numeric,
                    power(
                        10001::numeric,
                        (COALESCE(NULLIF(s.tempo, 0), 360) + 1) / 2629800.0
                    )
                ),
                2629800.0 / (COALESCE(NULLIF(s.tempo, 0), 360) + 1)
             ) - 1) * 100,
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
]

# Reverse: restore the 0011 ratio-clamped (still overflow-prone) view.
EPOCHS_VIEW_RATIO_CLAMPED = [
    "DROP MATERIALIZED VIEW IF EXISTS mv_subnet_validator_apy_epochs;",
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
            (power(
                1 + LEAST(ns.alpha_dividends::numeric / ns.alpha_stake::numeric, 1000::numeric),
                2629800.0 / (COALESCE(NULLIF(s.tempo, 0), 360) + 1)
             ) - 1) * 100,
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
]
# fmt: on


class Migration(migrations.Migration):
    # CREATE MATERIALIZED VIEW WITH DATA must not run inside the migration's
    # transaction (it runs the full SELECT and we raise work_mem per session).
    atomic = False

    dependencies = [
        ("metagraph", "0011_optimize_apy_refresh"),
    ]

    operations = [
        migrations.RunSQL(
            sql=EPOCHS_VIEW_BASE_CLAMPED,
            reverse_sql=EPOCHS_VIEW_RATIO_CLAMPED,
        ),
    ]
