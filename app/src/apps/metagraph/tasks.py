"""Celery tasks for metagraph data processing."""

import structlog
from celery import shared_task
from django.db import connection

logger = structlog.get_logger()


@shared_task(name="metagraph.refresh_apy_materialized_view")
def refresh_apy_materialized_view() -> dict:
    """
    Refresh the validator APY materialized view.

    This task should be run periodically (e.g., daily) to update the
    pre-calculated APY statistics for all validators.

    Returns:
        Dict with refresh status and timing info.

    """
    import time

    start_time = time.time()

    try:
        with connection.cursor() as cursor:
            # Use CONCURRENTLY to allow reads during refresh (requires unique index)
            cursor.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_validator_weekly_apy")

        duration = time.time() - start_time
        logger.info(
            "Refreshed APY materialized view",
            duration_seconds=round(duration, 2),
        )

        return {
            "status": "success",
            "duration_seconds": round(duration, 2),
        }

    except Exception as e:
        duration = time.time() - start_time
        logger.exception(
            "Failed to refresh APY materialized view",
            duration_seconds=round(duration, 2),
            error=str(e),
        )
        raise


@shared_task(name="metagraph.get_top_validators_by_apy")
def get_top_validators_by_apy(limit: int = 5) -> list[dict]:
    """
    Get the top validators by weekly APY across all subnets.

    This task queries the materialized view to get the best performing
    validators from the current week.

    Args:
        limit: Number of top validators to return per subnet.

    Returns:
        List of validator APY data grouped by subnet.

    """
    from django.db import connection

    query = """
    WITH ranked AS (
        SELECT
            netuid,
            subnet_name,
            hotkey,
            weekly_apy,
            emissions_tao,
            stake_tao,
            snapshot_count,
            ROW_NUMBER() OVER (PARTITION BY netuid ORDER BY weekly_apy DESC) AS rank
        FROM mv_validator_weekly_apy
        WHERE week_start = DATE_TRUNC('week', NOW())
          AND weekly_apy > 0
    )
    SELECT
        netuid,
        subnet_name,
        hotkey,
        weekly_apy,
        emissions_tao,
        stake_tao,
        snapshot_count,
        rank
    FROM ranked
    WHERE rank <= %s
    ORDER BY netuid, rank
    """

    with connection.cursor() as cursor:
        cursor.execute(query, [limit])
        columns = [col[0] for col in cursor.description]
        results = [dict(zip(columns, row)) for row in cursor.fetchall()]

    logger.info(
        "Retrieved top validators by APY",
        total_results=len(results),
        limit_per_subnet=limit,
    )

    return results
