"""Create mv_subnet_validator_apy_epochs: per-(subnet, validator, epoch) APY.

One row per validator per epoch (end-of-epoch snapshot only), computing the
accurate dТАО single-epoch-annualized APY directly from the net index-71
alpha dividends — no reconstruction correction factors. Backs the per-epoch
APY time-series chart. Wired into the `refresh_validator_apy_windows` beat task
(alongside mv_validator_apy_windows) in the following change.

Tempo note: `COALESCE(NULLIF(s.tempo, 0), 360)` falls back to 360 (Bittensor's
standard tempo) when Subnet.tempo was never populated. This is an intentional
divergence from the SDK's `single_epoch_apy`, which returns 0.0 for tempo <= 0 —
here 360 yields a correct chart instead of a spurious 0. Do not "fix" it to match
the SDK.
"""

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE MATERIALIZED VIEW WITH DATA runs the full SELECT;
    # keep it outside the migration transaction so a slow build
    # doesn't hold locks beyond what the refresh itself needs.

    dependencies = [
        ("metagraph", "0009_add_apy_data_points"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
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

            CREATE UNIQUE INDEX idx_mv_subnet_validator_apy_epochs_pk
                ON mv_subnet_validator_apy_epochs (subnet_id, neuron_id, epoch_block);

            CREATE INDEX idx_mv_subnet_validator_apy_epochs_subnet_ts
                ON mv_subnet_validator_apy_epochs (subnet_id, epoch_ts);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS mv_subnet_validator_apy_epochs;",
        ),
    ]
