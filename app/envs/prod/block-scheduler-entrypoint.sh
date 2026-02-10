#!/bin/sh
set -eu

# Block Scheduler Entrypoint
# Runs based on SENTINEL_MODE environment variable:
#   - live: Real-time block processing (block_tasks_v1)
#   - backfill: Legacy full metagraph backfill (backfill_blocks_v1)
#   - fast_backfill: Fast APY-only backfill with single tasks (fast_backfill)
#   - apy_backfill: Fast APY-only backfill with batch tasks (fast_backfill --async)

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
        BACKFILL_BATCH_SIZE="${BACKFILL_BATCH_SIZE:-10}"
        BACKFILL_BATCH_DELAY="${BACKFILL_BATCH_DELAY:-1.0}"

        echo "Starting block scheduler in FAST BACKFILL mode..."
        echo "  Block range: $BLOCK_START -> $BLOCK_END"
        echo "  Netuid: ${NETUID:-all configured}"
        echo "  Step: $BACKFILL_STEP"
        echo "  Batch size: $BACKFILL_BATCH_SIZE, delay: ${BACKFILL_BATCH_DELAY}s"
        echo "  Archive node: $BITTENSOR_ARCHIVE_NETWORK"

        EXTRA_ARGS=""
        if [ -n "${NETUID:-}" ]; then
            EXTRA_ARGS="$EXTRA_ARGS --netuid=$NETUID"
        fi

        # shellcheck disable=SC2086
        exec nice python manage.py fast_backfill \
            --from-block="$BLOCK_START" \
            --to-block="$BLOCK_END" \
            --network="$BITTENSOR_ARCHIVE_NETWORK" \
            --step="$BACKFILL_STEP" \
            --lite \
            $EXTRA_ARGS
        ;;
    apy_backfill)
        # APY backfill mode: Uses batch Celery tasks for efficient parallel processing
        # Each batch task processes multiple blocks with a single bittensor connection
        if [ -z "${BLOCK_START:-}" ] || [ -z "${BLOCK_END:-}" ]; then
            echo "ERROR: BLOCK_START and BLOCK_END are required for apy_backfill mode"
            exit 1
        fi

        if [ -z "${BITTENSOR_ARCHIVE_NETWORK:-}" ]; then
            echo "ERROR: BITTENSOR_ARCHIVE_NETWORK is required for apy_backfill mode"
            exit 1
        fi

        BACKFILL_STEP="${BACKFILL_STEP:-1}"
        BACKFILL_BATCH_SIZE="${BACKFILL_BATCH_SIZE:-50}"
        BACKFILL_BATCH_DELAY="${BACKFILL_BATCH_DELAY:-0.5}"

        echo "Starting block scheduler in APY BACKFILL mode..."
        echo "  Block range: $BLOCK_START -> $BLOCK_END"
        echo "  Netuid: ${NETUID:-all configured}"
        echo "  Step: $BACKFILL_STEP"
        echo "  Batch size: $BACKFILL_BATCH_SIZE blocks per task"
        echo "  Batch delay: ${BACKFILL_BATCH_DELAY}s between dispatches"
        echo "  Archive node: $BITTENSOR_ARCHIVE_NETWORK"

        EXTRA_ARGS=""
        if [ -n "${NETUID:-}" ]; then
            EXTRA_ARGS="$EXTRA_ARGS --netuid=$NETUID"
        fi

        # shellcheck disable=SC2086
        exec nice python manage.py fast_backfill \
            --from-block="$BLOCK_START" \
            --to-block="$BLOCK_END" \
            --network="$BITTENSOR_ARCHIVE_NETWORK" \
            --step="$BACKFILL_STEP" \
            --batch-size="$BACKFILL_BATCH_SIZE" \
            --batch-delay="$BACKFILL_BATCH_DELAY" \
            --lite \
            --async \
            $EXTRA_ARGS
        ;;
    *)
        echo "ERROR: Invalid SENTINEL_MODE '$SENTINEL_MODE'. Use 'live', 'backfill', 'fast_backfill', or 'apy_backfill'"
        exit 1
        ;;
esac
