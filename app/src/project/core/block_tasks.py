import os
from datetime import UTC, datetime

import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.dto import ExtrinsicDTO
from sentinel.v1.providers.bittensor import BittensorProvider, bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from project.core.services import JsonLinesStorage

logger = structlog.get_logger()

# Number of blocks behind current head after which archive node is required
ARCHIVE_THRESHOLD_BLOCKS = 300


def get_provider_for_block(block_number: int) -> BittensorProvider:
    """
    Get the appropriate provider for a block.

    Uses archive node for blocks older than ARCHIVE_THRESHOLD_BLOCKS.
    """
    archive_uri = os.getenv("BITTENSOR_ARCHIVE_NETWORK")
    if not archive_uri:
        return bittensor_provider()

    # Get current block to determine if we need archive
    with bittensor_provider() as provider:
        current_block = provider.get_current_block()

    if current_block - block_number > ARCHIVE_THRESHOLD_BLOCKS:
        logger.info(
            "Using archive node for old block",
            block_number=block_number,
            current_block=current_block,
            threshold=ARCHIVE_THRESHOLD_BLOCKS,
        )
        return bittensor_provider(archive_uri)

    return bittensor_provider()


@block_task(celery_kwargs={"rate_limit": "10/m"})
def store_block_extrinsics(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    with get_provider_for_block(block_number) as provider:
        service = sentinel_service(provider)
        block = service.ingest_block(block_number)
        extrinsics = block.extrinsics
        timestamp = block.timestamp

    if not extrinsics:
        logger.info("No extrinsics found in block", block_number=block_number)
        return ""

    extrinsic_records = store_extrinsics(extrinsics, block_number, timestamp)
    return f"Block {block_number} stored {extrinsic_records} extrinsics."


def store_extrinsics(extrinsics: list[ExtrinsicDTO], block_number: int, timestamp: int | None) -> int:
    """
    Store extrinsics from the given block number.
    """
    extrinsics_storage = JsonLinesStorage("data/bittensor/extrinsics/{date}.jsonl")
    if not extrinsics:
        return 0

    # Convert timestamp to date string for partitioning (timestamp is in milliseconds)
    date_str = datetime.fromtimestamp(timestamp / 1000, tz=UTC).strftime("%Y-%m-%d") if timestamp else "unknown"

    logger.info(
        "Storing extrinsics",
        block_number=block_number,
        extrinsics_count=len(extrinsics),
    )

    for extrinsic in extrinsics:
        extrinsics_storage.append(
            {
                "block_number": block_number,
                "timestamp": timestamp,
                **extrinsic.model_dump(),
            },
            date=date_str,
        )
    return len(extrinsics)
