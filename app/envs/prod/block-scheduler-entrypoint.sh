#!/bin/sh
set -eu

# Block Scheduler Entrypoint
# Runs either live mode (block_tasks_v1), backfill mode (backfill_blocks_v1),
# or fast_backfill mode (fast_backfill) based on SENTINEL_MODE environment variable

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
    fast_backfill)
        if [ -z "${BLOCK_START:-}" ] || [ -z "${BLOCK_END:-}" ]; then
            echo "ERROR: BLOCK_START and BLOCK_END are required for fast_backfill mode"
            exit 1
        fi

        if [ -z "${BITTENSOR_ARCHIVE_NETWORK:-}" ]; then
            echo "ERROR: BITTENSOR_ARCHIVE_NETWORK is required for fast_backfill mode"
            exit 1
        fi

        BACKFILL_STEP="${BACKFILL_STEP:-1}"

        echo "Starting block scheduler in FAST BACKFILL mode..."
        echo "  Block range: $BLOCK_START -> $BLOCK_END"
        echo "  Netuid: ${NETUID:-all configured}"
        echo "  Step: $BACKFILL_STEP"
        echo "  Archive node: $BITTENSOR_ARCHIVE_NETWORK"

        EXTRA_ARGS=""
        if [ -n "${NETUID:-}" ]; then
            EXTRA_ARGS="$EXTRA_ARGS --netuid=$NETUID"
        fi

        exec nice python manage.py fast_backfill \
            --from-block="$BLOCK_START" \
            --to-block="$BLOCK_END" \
            --network="$BITTENSOR_ARCHIVE_NETWORK" \
            --step="$BACKFILL_STEP" \
            --lite \
            "$EXTRA_ARGS"
        ;;
    *)
        echo "ERROR: Invalid SENTINEL_MODE '$SENTINEL_MODE'. Use 'live', 'backfill', or 'fast_backfill'"
        exit 1
        ;;
esac
