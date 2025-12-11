from datetime import UTC, datetime

import sentinel.v1.services.extractors.extrinsics.filters as extrinsics_filters
import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.dto import ExtrinsicDTO
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from project.core.services import JsonLinesStorage

logger = structlog.get_logger()


@block_task(celery_kwargs={"rate_limit": "10/m"})
def store_blockchain_data(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    service = sentinel_service(bittensor_provider())
    block = service.ingest_block(block_number)
    extrinsics = block.extrinsics

    # Extract timestampt extrinsics to store events with proper timestamps
    hyperparam_extrinsics = store_hyperparam_extrinsics(extrinsics, block_number, block.timestamp)
    set_weights_extrinsics = store_set_weights_extrinsics(extrinsics, block_number, block.timestamp)

    return f"{hyperparam_extrinsics}\n{set_weights_extrinsics}".strip()


def store_hyperparam_extrinsics(extrinsics: list[ExtrinsicDTO], block_number: int, timestamp: int | None) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    hyperparams_storage = JsonLinesStorage("data/bittensor/hyperparams-extrinsics.jsonl")
    hyperparam_extrinsics = extrinsics_filters.filter_hyperparam_extrinsics(extrinsics)
    if not hyperparam_extrinsics:
        return ""

    logger.info(
        "Storing hyperparameter extrinsics",
        block_number=block_number,
        extrinsics_count=len(hyperparam_extrinsics),
    )

    for extrinsic in hyperparam_extrinsics:
        hyperparams_storage.append({
            "block_number": block_number,
            "timestamp": timestamp,
            **extrinsic.model_dump(),
        })
    return f"Stored {len(hyperparam_extrinsics)} hyperparameter extrinsics from block {block_number}"


def store_set_weights_extrinsics(
    extrinsics: list[ExtrinsicDTO], block_number: int, timestamp: int | None,
) -> str:
    """
    Store extrinsics from the given block number that contain set_weights calls.
    Files are partitioned by date (YYYY-MM-DD) based on block timestamp.
    """
    weights_storage = JsonLinesStorage("data/bittensor/set-weights-extrinsics/{date}.jsonl")
    set_weights_extrinsics = extrinsics_filters.filter_weight_set_extrinsics(extrinsics)
    if not set_weights_extrinsics:
        return ""

    # Convert timestamp to date string for partitioning (timestamp is in milliseconds)
    date_str = datetime.fromtimestamp(timestamp / 1000, tz=UTC).strftime("%Y-%m-%d") if timestamp else "unknown"

    logger.info(
        "Storing set weights extrinsics",
        block_number=block_number,
        extrinsics_count=len(set_weights_extrinsics),
    )

    for extrinsic in set_weights_extrinsics:
        weights_storage.append({
            "block_number": block_number,
            "timestamp": timestamp,
            **extrinsic.model_dump(),
        }, date=date_str)
    return f"Stored {len(set_weights_extrinsics)} set_weights extrinsics from block {block_number}"
