from project.core.services.sentinel import block_ingestion_service


def test_block_ingestion_service_instance():
    sentinel_service = block_ingestion_service()
    ingestion = sentinel_service.ingest_block(100)
    assert ingestion.hyperparameters is not None
