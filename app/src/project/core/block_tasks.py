import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.extractors.extrinsics.filters import filter_hyperparam_extrinsics
from sentinel.v1.services.sentinel import sentinel_service

from project.core.services import JsonLinesStorage

logger = structlog.get_logger()



@block_task
def store_hyperparameters(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    hyperparams_storage = JsonLinesStorage("data/bittensor/hyperparams-extrinsics.jsonl")

    service = sentinel_service(bittensor_provider())
    block = service.ingest_block(block_number)
    hyperparam_extrinsics = filter_hyperparam_extrinsics(block.extrinsics)
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
