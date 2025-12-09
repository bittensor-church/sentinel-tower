import sentinel.v1.services.extractors.extrinsics.filters as extrinsics_filters
import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.providers.bittensor import bittensor_provider
from sentinel.v1.services.sentinel import sentinel_service

from project.core.services import JsonLinesStorage

logger = structlog.get_logger()


@block_task(celery_kwargs={"rate_limit": "10/m"})
def store_hyperparameters(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain hyperparameter updates.
    """
    hyperparams_storage = JsonLinesStorage("data/bittensor/hyperparams-extrinsics.jsonl")

    service = sentinel_service(bittensor_provider())
    block = service.ingest_block(block_number)
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


@block_task(celery_kwargs={"rate_limit": "10/m"})
def store_set_weights_extrinsics(block_number: int) -> str:
    """
    Store extrinsics from the given block number that contain set weight updates.
    """
    service = sentinel_service(bittensor_provider())
    block = service.ingest_block(block_number)

    set_weights_extrinsics = extrinsics_filters.filter_weight_set_extrinsics(block.extrinsics)
    if not set_weights_extrinsics:
        return "No set weights extrinsics found"

    logger.info(
        "Storing set weights extrinsics",
        block_number=block_number,
        extrinsics_count=len(set_weights_extrinsics),
    )

    netuids = set()
    for extrinsic in set_weights_extrinsics:
        netuid = extrinsic.netuid
        if netuid is None:
            logger.warning(
                "Skipping set weights extrinsic with missing netuid",
                block_number=block_number,
                extrinsic=extrinsic.model_dump(),
            )
            continue
        weights_storage = JsonLinesStorage(f"data/bittensor/netuid/{netuid}/set-weights-extrinsics.jsonl")
        weights_storage.append({"block_number": block_number, "netuid": netuid, **extrinsic.model_dump()})
        netuids.add(netuid)

    return (
        f"Stored {len(set_weights_extrinsics)} set weights extrinsics from block {block_number} "
        f"across netuids: {sorted(netuids)}"
    )
