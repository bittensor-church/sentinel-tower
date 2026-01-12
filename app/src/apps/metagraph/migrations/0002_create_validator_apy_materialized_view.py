"""Create materialized view for validator weekly APY calculations."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metagraph", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE MATERIALIZED VIEW IF NOT EXISTS mv_validator_weekly_apy AS
            WITH weekly_stats AS (
                SELECT
                    n.id AS neuron_id,
                    n.subnet_id AS netuid,
                    n.hotkey_id,
                    h.hotkey,
                    s.name AS subnet_name,
                    DATE_TRUNC('week', b.timestamp) AS week_start,
                    SUM(ns.emissions) AS total_emissions,
                    AVG(ns.total_stake) AS avg_stake,
                    COUNT(*) AS snapshot_count,
                    MIN(b.timestamp) AS first_snapshot,
                    MAX(b.timestamp) AS last_snapshot
                FROM metagraph_neuron_snapshot ns
                JOIN metagraph_neuron n ON ns.neuron_id = n.id
                JOIN metagraph_hotkey h ON n.hotkey_id = h.id
                JOIN metagraph_subnet s ON n.subnet_id = s.netuid
                JOIN metagraph_block b ON ns.block_id = b.number
                WHERE ns.is_validator = TRUE
                  AND ns.total_stake > 0
                  AND b.timestamp IS NOT NULL
                GROUP BY n.id, n.subnet_id, n.hotkey_id, h.hotkey, s.name, DATE_TRUNC('week', b.timestamp)
            )
            SELECT
                neuron_id,
                netuid,
                hotkey_id,
                hotkey,
                subnet_name,
                week_start,
                total_emissions,
                avg_stake,
                snapshot_count,
                first_snapshot,
                last_snapshot,
                CASE
                    WHEN avg_stake > 0
                    THEN (total_emissions::NUMERIC / avg_stake) * 52 * 100
                    ELSE 0
                END AS weekly_apy,
                total_emissions / 1e9 AS emissions_tao,
                avg_stake / 1e9 AS stake_tao
            FROM weekly_stats;

            -- Create unique index for concurrent refresh
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_validator_apy_unique
                ON mv_validator_weekly_apy(neuron_id, week_start);

            -- Create indexes for fast queries
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_week
                ON mv_validator_weekly_apy(week_start);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_netuid
                ON mv_validator_weekly_apy(netuid);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_hotkey
                ON mv_validator_weekly_apy(hotkey);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_weekly_apy
                ON mv_validator_weekly_apy(weekly_apy DESC);
            """,
            reverse_sql="""
            DROP MATERIALIZED VIEW IF EXISTS mv_validator_weekly_apy;
            """,
        ),
    ]
