import sentinel.v1.services.extractors.extrinsics.filters as extrinsics_filters
import structlog
from abstract_block_dumper.v1.decorators import block_task
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

    hyperparam_extrinsics = store_hyperparam_extrinsics(block, block_number)
    set_weights_extrinsics = store_set_weights_extrinsics(block, block_number)

    return f"{hyperparam_extrinsics}\n{set_weights_extrinsics}".strip()


def store_hyperparam_extrinsics(block, block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    hyperparams_storage = JsonLinesStorage("data/bittensor/hyperparams-extrinsics.jsonl")
    hyperparam_extrinsics = extrinsics_filters.filter_hyperparam_extrinsics(block.extrinsics)
    if not hyperparam_extrinsics:
        return ""

    logger.info(
        "Storing hyperparameter extrinsics",
        block_number=block_number,
        extrinsics_count=len(hyperparam_extrinsics),
    )

    for extrinsic in hyperparam_extrinsics:
        hyperparams_storage.append({"block_number": block_number, **extrinsic.model_dump()})
    return f"Stored {len(hyperparam_extrinsics)} hyperparameter extrinsics from block {block_number}"


def store_set_weights_extrinsics(block, block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain set_weights calls.
    """
    weights_storage = JsonLinesStorage("data/bittensor/set-weights-extrinsics.jsonl")
    set_weights_extrinsics = extrinsics_filters.filter_weight_set_extrinsics(block.extrinsics)
    if not set_weights_extrinsics:
        return ""

    logger.info(
        "Storing set weights extrinsics",
        block_number=block_number,
        extrinsics_count=len(set_weights_extrinsics),
    )

    for extrinsic in set_weights_extrinsics:
        weights_storage.append({"block_number": block_number, **extrinsic.model_dump()})
    return f"Stored {len(set_weights_extrinsics)} set_weights extrinsics from block {block_number}"