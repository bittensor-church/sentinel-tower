"""Drop mv_validator_weekly_apy materialized view."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("metagraph", "0005_add_query_performance_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP MATERIALIZED VIEW IF EXISTS mv_validator_weekly_apy;",
            reverse_sql="""
            CREATE MATERIALIZED VIEW mv_validator_weekly_apy AS
            WITH weekly_stats AS (
                SELECT
                    n.id AS neuron_id,
                    n.subnet_id AS netuid,
                    n.hotkey_id,
                    h.hotkey,
                    s.name AS subnet_name,
                    DATE_TRUNC('week', b.timestamp) AS week_start,
                    AVG(ns.dividend_apy) AS avg_dividend_apy,
                    SUM(ns.emissions) AS total_emissions,
                    AVG(ns.total_stake) AS avg_stake,
                    AVG(ns.alpha_stake) AS avg_alpha_stake,
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
                GROUP BY n.id, n.subnet_id, n.hotkey_id, h.hotkey, s.name,
                         DATE_TRUNC('week', b.timestamp)
            )
            SELECT
                neuron_id,
                netuid,
                hotkey_id,
                hotkey,
                subnet_name,
                week_start,
                avg_dividend_apy AS weekly_apy,
                total_emissions,
                avg_stake,
                avg_alpha_stake,
                snapshot_count,
                first_snapshot,
                last_snapshot,
                total_emissions / 1e9 AS emissions_tao,
                avg_stake / 1e9 AS stake_tao,
                avg_alpha_stake / 1e9 AS alpha_stake_tao
            FROM weekly_stats;

            CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_validator_apy_unique
                ON mv_validator_weekly_apy(neuron_id, week_start);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_week
                ON mv_validator_weekly_apy(week_start);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_netuid
                ON mv_validator_weekly_apy(netuid);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_hotkey
                ON mv_validator_weekly_apy(hotkey);
            CREATE INDEX IF NOT EXISTS idx_mv_validator_apy_weekly_apy
                ON mv_validator_weekly_apy(weekly_apy DESC);
            """,
        ),
    ]
