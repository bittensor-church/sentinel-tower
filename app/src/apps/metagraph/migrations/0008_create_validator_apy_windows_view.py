"""Create mv_validator_apy_windows materialized view for the dashboard.

Pre-aggregates per-(subnet, validator-neuron) APY over the latest 1h/1d/1w/1m
windows, anchored on the most recent block timestamp. Refreshed every 15 min
by the `refresh_validator_apy_windows` Celery task (see apps.metagraph.tasks).

Replaces the ad-hoc CTE query in the Grafana validator-APY panel, which took
~50s per subnet and was being cancelled by Grafana's default plugin timeout.
"""

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE MATERIALIZED VIEW with data runs the full SELECT;
                    # keep it outside the migration transaction so a slow build
                    # doesn't hold locks beyond what the refresh itself needs.

    dependencies = [
        ("metagraph", "0007_drop_unused_indexes"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE MATERIALIZED VIEW mv_validator_apy_windows AS
            WITH global_anchor AS (
                SELECT MAX(timestamp) AS end_t FROM metagraph_block
            ),
            snapshot_apy AS (
                SELECT
                    n.subnet_id, ns.id AS snapshot_id, ns.neuron_id,
                    ns.alpha_stake, ns.total_stake, b.timestamp AS block_ts,
                    CASE
                        WHEN ns.alpha_stake > 0 THEN
                            (CASE WHEN mm.dividend > 1 THEN mm.dividend / 65535.0 ELSE mm.dividend END)
                            * (COALESCE(NULLIF(s.alpha_out_emission, 0), 1e9)::numeric / ns.alpha_stake::numeric)
                            * (1 - COALESCE(s.owner_cut, 0.09))
                            * 0.5 * 2629800 * 100
                        ELSE 0
                    END AS apy_pct
                FROM metagraph_neuron_snapshot ns
                JOIN metagraph_neuron     n  ON n.id     = ns.neuron_id
                JOIN metagraph_subnet     s  ON s.netuid = n.subnet_id
                JOIN metagraph_block      b  ON b.number = ns.block_id
                LEFT JOIN metagraph_mechanism_metrics mm
                       ON mm.snapshot_id = ns.id AND mm.mech_id = 0
                WHERE ns.is_validator = true
                  AND b.timestamp >= (SELECT end_t - INTERVAL '1 month' FROM global_anchor)
            ),
            latest_snapshot AS (
                SELECT DISTINCT ON (sa.subnet_id, sa.neuron_id)
                    sa.subnet_id, sa.neuron_id, h.hotkey,
                    COALESCE(NULLIF(h.label, ''), LEFT(h.hotkey, 8) || '...') AS validator_name,
                    sa.alpha_stake / 1e9 AS alpha_stake_tao,
                    sa.total_stake / 1e9 AS stake_tao
                FROM snapshot_apy sa
                JOIN metagraph_neuron n ON n.id = sa.neuron_id
                JOIN metagraph_hotkey h ON h.id = n.hotkey_id
                ORDER BY sa.subnet_id, sa.neuron_id, sa.block_ts DESC
            ),
            apy_windows AS (
                SELECT
                    sa.subnet_id, sa.neuron_id,
                    AVG(sa.apy_pct) FILTER (WHERE sa.block_ts >= (SELECT end_t - INTERVAL '1 hour' FROM global_anchor)) AS apy_1h,
                    AVG(sa.apy_pct) FILTER (WHERE sa.block_ts >= (SELECT end_t - INTERVAL '1 day'  FROM global_anchor)) AS apy_1d,
                    AVG(sa.apy_pct) FILTER (WHERE sa.block_ts >= (SELECT end_t - INTERVAL '1 week' FROM global_anchor)) AS apy_1w,
                    AVG(sa.apy_pct) AS apy_1m
                FROM snapshot_apy sa
                GROUP BY sa.subnet_id, sa.neuron_id
            )
            SELECT
                ls.subnet_id, ls.neuron_id, ls.validator_name, ls.hotkey,
                ls.alpha_stake_tao, ls.stake_tao,
                COALESCE(aw.apy_1h, 0) AS apy_1h,
                COALESCE(aw.apy_1d, 0) AS apy_1d,
                COALESCE(aw.apy_1w, 0) AS apy_1w,
                COALESCE(aw.apy_1m, 0) AS apy_1m
            FROM latest_snapshot ls
            LEFT JOIN apy_windows aw
                   ON aw.subnet_id = ls.subnet_id AND aw.neuron_id = ls.neuron_id
            WHERE ls.alpha_stake_tao > 0;

            CREATE UNIQUE INDEX idx_mv_validator_apy_windows_pk
                ON mv_validator_apy_windows (subnet_id, neuron_id);

            CREATE INDEX idx_mv_validator_apy_windows_subnet
                ON mv_validator_apy_windows (subnet_id);
            """,
            reverse_sql="DROP MATERIALIZED VIEW IF EXISTS mv_validator_apy_windows;",
        ),
    ]
