import structlog
from abstract_block_dumper.v1.decorators import block_task
from django.conf import settings

from sentinel.providers.bittensor import bittensor_provider
from sentinel.services.sentinel import sentinel_service
from sentinel.services.storage import create_local_json_storage

logger = structlog.get_logger()

@block_task(
    condition=lambda _bn: True,
)
def store_hyperparameters(block_number: int) -> list[str]:
    """
    A block task that processes every block and stores hyperparameters.

    The storage backend and format are configured via environment variables.
    See _get_storage_service() for configuration options.

    """
    batch_processing = []
    for netuid in [17, 19, 21]:
        sentinel = sentinel_service(bittensor_provider())

        # Collect hyperparameter values
        block = sentinel.ingest_block(block_number, netuid)

        # Store result with organized path structure

        storage_service = create_local_json_storage(f"{settings.MEDIA_ROOT}/data/hyperparams")
        stored_path = storage_service.store(
            block_number, netuid, block.hyperparameters, f"subnet_{netuid}/block_{block_number}",
        )

        logger.info(
            "Stored hyperparameters",
            block_number=block_number,
            netuid=netuid,
            stored_path=stored_path,
            hyperparameters=block.hyperparameters.model_dump(),
        )
        batch_processing.append(stored_path)

    return batch_processing
