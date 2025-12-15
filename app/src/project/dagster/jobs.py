"""Dagster jobs and sensors for automated data ingestion."""

from collections.abc import Generator
from datetime import UTC, datetime

import dagster as dg

from project.core.models import Extrinsic, HyperparamEvent, IngestionCheckpoint
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

        # Convert milliseconds timestamp to datetime
        timestamp_ms = record.get("timestamp")
        timestamp_dt = (
            datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC) if timestamp_ms else None
        )

        obj, created = HyperparamEvent.objects.get_or_create(
            extrinsic_hash=extrinsic_hash,
            defaults={
                "block_number": record.get("block_number", 0),
                "timestamp": timestamp_dt,
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
            # Backfill timestamp for existing records
            if obj.timestamp is None and timestamp_dt is not None:
                obj.timestamp = timestamp_dt
                obj.save(update_fields=["timestamp"])
            skipped_count += 1

    # Update checkpoint
    checkpoint.last_processed_line = last_line
    checkpoint.save()

    context.log.info(f"Ingested {created_count} hyperparameter events, skipped {skipped_count} duplicates")
    return {"processed": created_count, "skipped": skipped_count}


def _sanitize_json(obj: object) -> object:
    r"""Remove null bytes from JSON data (PostgreSQL JSONB doesn't support \u0000)."""
    if isinstance(obj, str):
        return obj.replace("\x00", "")
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(item) for item in obj]
    return obj


def _parse_extrinsic_record(record: dict) -> dict | None:
    """Parse a JSONL record into Extrinsic model fields."""
    extrinsic_hash = record.get("extrinsic_hash", "")
    if not extrinsic_hash:
        return None

    call_data = record.get("call", {})
    call_args_list = call_data.get("call_args", [])

    # Extract netuid from record or call_args
    netuid = record.get("netuid")
    if netuid is None:
        for arg in call_args_list:
            if arg.get("name") == "netuid":
                netuid = arg.get("value")
                break

    # Determine success from status
    status = record.get("status", "")
    success = status.lower() == "success"

    # Extract error data from events if failed
    error_data = None
    events = record.get("events", [])
    if not success:
        for event in events:
            if event.get("event_id") == "ExtrinsicFailed":
                error_data = event.get("attributes")
                break

    return {
        "extrinsic_hash": extrinsic_hash,
        "block_number": record.get("block_number", 0),
        "block_timestamp": record.get("timestamp"),
        "extrinsic_index": record.get("index"),
        "call_module": call_data.get("call_module", ""),
        "call_function": call_data.get("call_function", ""),
        "call_args": _sanitize_json(call_args_list),
        "address": record.get("address") or "",
        "signature": _sanitize_json(record.get("signature")),
        "nonce": record.get("nonce"),
        "tip_rao": record.get("tip"),
        "success": success,
        "status": status,
        "error_data": _sanitize_json(error_data),
        "events": _sanitize_json(events),
        "netuid": netuid,
    }


@dg.op
def ingest_extrinsics(context: dg.OpExecutionContext, jsonl_reader: JsonLinesReader) -> dict:
    """Ingest all extrinsics from partitioned JSONL files to the Extrinsic model."""
    checkpoint, _ = IngestionCheckpoint.objects.get_or_create(
        file_path=f"{SET_WEIGHTS_DIR}/extrinsics",
        defaults={"last_processed_line": 0},
    )

    records, total_lines = jsonl_reader.read_set_weights()

    if not records:
        context.log.info("No extrinsic records found")
        return {"processed": 0, "skipped": 0}

    if total_lines <= checkpoint.last_processed_line:
        context.log.info("No new extrinsic records to process")
        return {"processed": 0, "skipped": 0}

    created_count = 0
    skipped_count = 0

    for record in records:
        parsed = _parse_extrinsic_record(record)
        if parsed is None:
            skipped_count += 1
            continue

        extrinsic_hash = parsed.pop("extrinsic_hash")
        _, created = Extrinsic.objects.get_or_create(
            extrinsic_hash=extrinsic_hash,
            defaults=parsed,
        )

        if created:
            created_count += 1
        else:
            skipped_count += 1

    checkpoint.last_processed_line = total_lines
    checkpoint.save()

    context.log.info("Ingested %d extrinsics, skipped %d duplicates", created_count, skipped_count)
    return {"processed": created_count, "skipped": skipped_count}


@dg.job(description="Ingest hyperparameter events from JSONL to database")
def ingest_hyperparams_job():
    """Job to ingest hyperparameter events."""
    ingest_hyperparams()


@dg.job(description="Ingest all extrinsics from JSONL to Extrinsic model")
def ingest_extrinsics_job() -> None:
    """Job to ingest all extrinsics to the generic Extrinsic table."""
    ingest_extrinsics()


@dg.job(description="Ingest all blockchain events from JSONL to database")
def ingest_all_events_job():
    """Job to ingest all event types."""
    ingest_hyperparams()
    ingest_extrinsics()


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


@dg.sensor(job=ingest_extrinsics_job, minimum_interval_seconds=60)
def extrinsics_sensor(
    context: dg.SensorEvaluationContext,
    jsonl_reader: JsonLinesReader,
) -> Generator[dg.RunRequest, None, None]:
    """Sensor to detect new extrinsics and trigger ingestion to Extrinsic model."""
    current_lines = jsonl_reader.count_partitioned_lines(SET_WEIGHTS_DIR)
    last_cursor = int(context.cursor) if context.cursor else 0

    new_count = current_lines - last_cursor
    if new_count > 0:
        context.log.info("Found %d new extrinsic records", new_count)
        yield dg.RunRequest(run_key=f"extrinsics-{current_lines}")
        context.update_cursor(str(current_lines))


# Schedule for periodic full sync (runs every hour as backup)
@dg.schedule(job=ingest_all_events_job, cron_schedule="0 * * * *")
def hourly_ingest_schedule():
    """Hourly backup schedule to ensure all records are ingested."""
    return {}
