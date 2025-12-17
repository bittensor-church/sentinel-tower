from datetime import UTC, datetime

import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.dto import ExtrinsicDTO
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from project.core.services import JsonLinesStorage

logger = structlog.get_logger()


@block_task(celery_kwargs={"rate_limit": "10/m"})
def store_block_extrinsics(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    service = sentinel_service(bittensor_provider())
    block = service.ingest_block(block_number)
    extrinsics = block.extrinsics
    if not extrinsics:
        logger.info("No extrinsics found in block", block_number=block_number)
        return ""

    extrinsic_records = store_extrinsics(extrinsics, block_number, block.timestamp)
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
