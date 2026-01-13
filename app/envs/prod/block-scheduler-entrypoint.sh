#!/bin/sh
set -eu

# Block Scheduler Entrypoint
# Runs either live mode (block_tasks_v1) or backfill mode (backfill_blocks_v1)
# based on SENTINEL_MODE environment variable

SENTINEL_MODE="${SENTINEL_MODE:-live}"

case "$SENTINEL_MODE" in
    live)
        echo "Starting block scheduler in LIVE mode..."
        exec nice python manage.py block_tasks_v1
        ;;
    backfill)
        if [ -z "${BLOCK_START:-}" ] || [ -z "${BLOCK_END:-}" ]; then
            echo "ERROR: BLOCK_START and BLOCK_END are required for backfill mode"
            exit 1
        fi

        if [ -z "${BITTENSOR_ARCHIVE_NETWORK:-}" ]; then
            echo "ERROR: BITTENSOR_ARCHIVE_NETWORK is required for backfill mode"
            exit 1
        fi

        BACKFILL_RATE_LIMIT="${BACKFILL_RATE_LIMIT:-1.0}"

        echo "Starting block scheduler in BACKFILL mode..."
        echo "  Block range: $BLOCK_START -> $BLOCK_END"
        echo "  Rate limit: $BACKFILL_RATE_LIMIT seconds"
        echo "  Archive node: $BITTENSOR_ARCHIVE_NETWORK"

        exec nice python manage.py backfill_blocks_v1 \
            --from-block="$BLOCK_START" \
            --to-block="$BLOCK_END" \
            --rate-limit="$BACKFILL_RATE_LIMIT"
        ;;
    *)
        echo "ERROR: Invalid SENTINEL_MODE '$SENTINEL_MODE'. Use 'live' or 'backfill'"
        exit 1
        ;;
esac
