"""Dagster jobs and sensors for automated data ingestion."""

import dagster as dg

from project.core.models import HyperparamEvent, IngestionCheckpoint, SetWeightsEvent
from project.dagster.resources import JsonLinesReader

HYPERPARAMS_FILE = "data/bittensor/hyperparams-extrinsics.jsonl"
SET_WEIGHTS_DIR = "data/bittensor/set-weights-extrinsics"


@dg.op
def ingest_hyperparams(context: dg.OpExecutionContext, jsonl_reader: JsonLinesReader) -> dict:
    """Ingest new hyperparameter events from JSONL to database."""
    checkpoint, _ = IngestionCheckpoint.objects.get_or_create(
        file_path=HYPERPARAMS_FILE,
        defaults={"last_processed_line": 0},
    )

    records, last_line = jsonl_reader.read_hyperparams(start_line=checkpoint.last_processed_line)

    if not records:
        context.log.info("No new hyperparameter records to process")
        return {"processed": 0, "skipped": 0}

    created_count = 0
    skipped_count = 0

    for record in records:
        extrinsic_hash = record.get("extrinsic_hash", "")
        if not extrinsic_hash:
            skipped_count += 1
            continue

        # Extract call info
        call_data = record.get("call", {})
        call_args_list = call_data.get("call_args", [])
        call_args_dict = {arg["name"]: arg["value"] for arg in call_args_list}

        # Extract netuid - check record level first, then call_args
        netuid = record.get("netuid")
        if netuid is None:
            netuid = call_args_dict.get("netuid")

        _, created = HyperparamEvent.objects.get_or_create(
            extrinsic_hash=extrinsic_hash,
            defaults={
                "block_number": record.get("block_number", 0),
                "call_function": call_data.get("call_function", ""),
                "call_module": call_data.get("call_module", ""),
                "netuid": netuid,
                "address": record.get("address"),
                "status": record.get("status"),
                "call_args": call_args_dict,
            },
        )

        if created:
            created_count += 1
        else:
            skipped_count += 1

    # Update checkpoint
    checkpoint.last_processed_line = last_line
    checkpoint.save()

    context.log.info(f"Ingested {created_count} hyperparameter events, skipped {skipped_count} duplicates")
    return {"processed": created_count, "skipped": skipped_count}


@dg.op
def ingest_set_weights(context: dg.OpExecutionContext, jsonl_reader: JsonLinesReader) -> dict:
    """Ingest new set_weights events from partitioned JSONL files to database."""
    checkpoint, _ = IngestionCheckpoint.objects.get_or_create(
        file_path=SET_WEIGHTS_DIR,
        defaults={"last_processed_line": 0},
    )

    # Read all records from partitioned files (deduplication handled by get_or_create)
    records, total_lines = jsonl_reader.read_set_weights()

    if not records:
        context.log.info("No set_weights records found")
        return {"processed": 0, "skipped": 0}

    # Skip if no new lines since last checkpoint
    if total_lines <= checkpoint.last_processed_line:
        context.log.info("No new set_weights records to process")
        return {"processed": 0, "skipped": 0}

    created_count = 0
    skipped_count = 0

    for record in records:
        extrinsic_hash = record.get("extrinsic_hash", "")
        if not extrinsic_hash:
            skipped_count += 1
            continue

        # Extract weights data from call args
        call_data = record.get("call", {})
        call_args_list = call_data.get("call_args", [])
        weights_data = {arg["name"]: arg["value"] for arg in call_args_list}

        # Extract netuid - check record level first, then call_args
        netuid = record.get("netuid")
        if netuid is None:
            netuid = weights_data.get("netuid")
        if netuid is None:
            skipped_count += 1
            continue

        # Extract events data
        events = record.get("events", [])

        _, created = SetWeightsEvent.objects.get_or_create(
            extrinsic_hash=extrinsic_hash,
            defaults={
                "block_number": record.get("block_number", 0),
                "netuid": netuid,
                "address": record.get("address"),
                "status": record.get("status"),
                "weights_data": weights_data,
                "events": events,
            },
        )

        if created:
            created_count += 1
        else:
            skipped_count += 1

    # Update checkpoint with total lines processed
    checkpoint.last_processed_line = total_lines
    checkpoint.save()

    context.log.info(f"Ingested {created_count} set_weights events, skipped {skipped_count} duplicates")
    return {"processed": created_count, "skipped": skipped_count}


@dg.job(description="Ingest hyperparameter events from JSONL to database")
def ingest_hyperparams_job():
    """Job to ingest hyperparameter events."""
    ingest_hyperparams()


@dg.job(description="Ingest set_weights events from JSONL to database")
def ingest_set_weights_job():
    """Job to ingest set_weights events."""
    ingest_set_weights()


@dg.job(description="Ingest all blockchain events from JSONL to database")
def ingest_all_events_job():
    """Job to ingest all event types."""
    ingest_hyperparams()
    ingest_set_weights()


@dg.sensor(job=ingest_hyperparams_job, minimum_interval_seconds=60)
def hyperparams_sensor(context: dg.SensorEvaluationContext, jsonl_reader: JsonLinesReader):
    """Sensor to detect new hyperparameter records and trigger ingestion."""
    current_lines = jsonl_reader.count_lines(HYPERPARAMS_FILE)
    last_cursor = int(context.cursor) if context.cursor else 0

    new_count = current_lines - last_cursor
    if new_count > 0:
        context.log.info(f"Found {new_count} new hyperparameter records")
        yield dg.RunRequest(run_key=f"hyperparams-{current_lines}")
        context.update_cursor(str(current_lines))


@dg.sensor(job=ingest_set_weights_job, minimum_interval_seconds=60)
def set_weights_sensor(context: dg.SensorEvaluationContext, jsonl_reader: JsonLinesReader):
    """Sensor to detect new set_weights records and trigger ingestion."""
    current_lines = jsonl_reader.count_partitioned_lines(SET_WEIGHTS_DIR)
    last_cursor = int(context.cursor) if context.cursor else 0

    new_count = current_lines - last_cursor
    if new_count > 0:
        context.log.info(f"Found {new_count} new set_weights records")
        yield dg.RunRequest(run_key=f"set_weights-{current_lines}")
        context.update_cursor(str(current_lines))


# Schedule for periodic full sync (runs every hour as backup)
@dg.schedule(job=ingest_all_events_job, cron_schedule="0 * * * *")
def hourly_ingest_schedule():
    """Hourly backup schedule to ensure all records are ingested."""
    return {}
