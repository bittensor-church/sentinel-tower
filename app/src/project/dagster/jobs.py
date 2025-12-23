"""Dagster jobs and sensors for automated data ingestion."""

from collections.abc import Generator

import dagster as dg

from project.core.models import Extrinsic, IngestionCheckpoint
from project.dagster.resources import JsonLinesReader

EXTRINSICS_DIR = "data/bittensor/extrinsics"


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
        file_path=EXTRINSICS_DIR,
        defaults={"last_processed_line": 0},
    )

    # Only read new records from checkpoint onwards (avoids loading all data into memory)
    start_line = checkpoint.last_processed_line
    records, total_lines = jsonl_reader.read_extrinsics(start_line=start_line)

    if total_lines < start_line:
        context.log.warning(
            "Extrinsics data shrank (checkpoint=%d, available=%d). Resetting checkpoint and re-reading from start.",
            start_line,
            total_lines,
        )
        checkpoint.last_processed_line = 0
        checkpoint.save(update_fields=["last_processed_line", "updated_at"])
        start_line = 0
        records, total_lines = jsonl_reader.read_extrinsics(start_line=start_line)

    if not records:
        if checkpoint.last_processed_line != total_lines:
            checkpoint.last_processed_line = total_lines
            checkpoint.save(update_fields=["last_processed_line", "updated_at"])
        context.log.info("No new extrinsic records to process (last checkpoint: %d)", total_lines)
        return {"processed": 0, "skipped": 0}

    # Parse all records first
    parsed_records: dict[str, dict] = {}
    skipped_count = 0

    for record in records:
        parsed = _parse_extrinsic_record(record)
        if parsed is None:
            skipped_count += 1
            continue
        extrinsic_hash = parsed.pop("extrinsic_hash")
        parsed_records[extrinsic_hash] = parsed

    if not parsed_records:
        context.log.info("No valid extrinsic records to process")
        return {"processed": 0, "skipped": skipped_count}

    # Get existing hashes in bulk
    existing_hashes = set(
        Extrinsic.objects.filter(extrinsic_hash__in=parsed_records.keys()).values_list(
            "extrinsic_hash",
            flat=True,
        ),
    )

    # Filter to only new records
    new_records = [
        Extrinsic(extrinsic_hash=h, **data) for h, data in parsed_records.items() if h not in existing_hashes
    ]

    skipped_count += len(existing_hashes)

    # Bulk create new records
    if new_records:
        batch_size = 1000
        for i in range(0, len(new_records), batch_size):
            batch = new_records[i : i + batch_size]
            Extrinsic.objects.bulk_create(batch, ignore_conflicts=True)

    created_count = len(new_records)

    checkpoint.last_processed_line = total_lines
    checkpoint.save()

    context.log.info("Ingested %d extrinsics, skipped %d duplicates", created_count, skipped_count)
    return {"processed": created_count, "skipped": skipped_count}


@dg.job(description="Ingest all extrinsics from JSONL to Extrinsic model")
def ingest_extrinsics_job() -> None:
    """Job to ingest all extrinsics to the Extrinsic table."""
    ingest_extrinsics()


@dg.sensor(job=ingest_extrinsics_job, minimum_interval_seconds=60)
def extrinsics_sensor(
    context: dg.SensorEvaluationContext,
    jsonl_reader: JsonLinesReader,
) -> Generator[dg.RunRequest | dg.SkipReason, None, None]:
    """Sensor to detect new extrinsics and trigger ingestion to Extrinsic model."""
    # Check if there's already a run in progress for this job
    in_progress_runs = context.instance.get_runs(
        filters=dg.RunsFilter(
            job_name=ingest_extrinsics_job.name,
            statuses=[
                dg.DagsterRunStatus.STARTED,
                dg.DagsterRunStatus.QUEUED,
                dg.DagsterRunStatus.STARTING,
            ],
        ),
        limit=1,
    )

    if in_progress_runs:
        yield dg.SkipReason("Previous run still in progress, waiting for completion")
        return

    # Use file size for efficient change detection (avoids counting all lines every minute)
    current_size = jsonl_reader.get_partitioned_total_size(EXTRINSICS_DIR)
    last_cursor = int(context.cursor) if context.cursor else 0

    if current_size < last_cursor:
        context.log.warning(
            "Extrinsics data size decreased (cursor=%d -> current=%d). Resetting cursor and triggering re-ingest.",
            last_cursor,
            current_size,
        )
        context.update_cursor(str(current_size))
        yield dg.RunRequest()
        return

    if current_size > last_cursor:
        context.log.info("Detected new extrinsic data (size: %d -> %d bytes)", last_cursor, current_size)
        yield dg.RunRequest(run_key=f"extrinsics-{current_size}")
        context.update_cursor(str(current_size))


# Schedule for periodic full sync (runs every hour as backup)
@dg.schedule(job=ingest_extrinsics_job, cron_schedule="0 * * * *")
def hourly_ingest_schedule():
    """Hourly backup schedule to ensure all records are ingested."""
    return {}


# Metagraph Ingestion

METAGRAPH_CHECKPOINT_PREFIX = "metagraph"


def _get_metagraph_checkpoint_key(netuid: int, block_number: int) -> str:
    """Generate a checkpoint key for a metagraph file."""
    return f"{METAGRAPH_CHECKPOINT_PREFIX}:{netuid}:{block_number}"


def _parse_metagraph_checkpoint_key(key: str) -> tuple[int, int] | None:
    """Parse a metagraph checkpoint key into (netuid, block_number)."""
    if not key.startswith(f"{METAGRAPH_CHECKPOINT_PREFIX}:"):
        return None
    parts = key.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


@dg.op
def ingest_metagraph(context: dg.OpExecutionContext, jsonl_reader: JsonLinesReader) -> dict:
    """Ingest all metagraph snapshots from JSONL files to Django models."""
    from apps.metagraph.services.sync_service import MetagraphSyncService

    all_files = jsonl_reader.list_all_metagraph_files()

    if not all_files:
        context.log.info("No metagraph files found")
        return {"processed": 0, "skipped": 0}

    # Get already processed files from checkpoints
    processed_keys = set(
        IngestionCheckpoint.objects.filter(
            file_path__startswith=f"{METAGRAPH_CHECKPOINT_PREFIX}:",
        ).values_list("file_path", flat=True),
    )

    # Filter to unprocessed files
    files_to_process = []
    for netuid, filename in all_files:
        block_number = int(filename.replace(".jsonl", ""))
        checkpoint_key = _get_metagraph_checkpoint_key(netuid, block_number)
        if checkpoint_key not in processed_keys:
            files_to_process.append((netuid, filename, block_number, checkpoint_key))

    if not files_to_process:
        context.log.info("No new metagraph files to process")
        return {"processed": 0, "skipped": len(all_files)}

    context.log.info("Found %d new metagraph files to process", len(files_to_process))

    processed_count = 0
    error_count = 0
    total_stats: dict[str, int] = {}

    for netuid, filename, block_number, checkpoint_key in files_to_process:
        try:
            data = jsonl_reader.read_metagraph_file(netuid, filename)
            if not data:
                context.log.warning("Empty metagraph file: %s/%s", netuid, filename)
                error_count += 1
                continue

            # Sync to Django models
            sync_service = MetagraphSyncService()
            stats = sync_service.sync_metagraph(data)

            # Aggregate stats
            for key, value in stats.items():
                total_stats[key] = total_stats.get(key, 0) + value

            # Mark as processed
            IngestionCheckpoint.objects.create(
                file_path=checkpoint_key,
                last_processed_line=1,
            )

            processed_count += 1
            context.log.info(
                "Processed metagraph netuid=%d block=%d: %s",
                netuid,
                block_number,
                stats,
            )

        except Exception:
            context.log.exception(
                "Error processing metagraph %s/%s: %s",
                netuid,
                filename,
                stack_info=True,
            )
            error_count += 1

    context.log.info(
        "Metagraph ingestion complete: processed=%d, errors=%d, stats=%s",
        processed_count,
        error_count,
        total_stats,
    )

    return {
        "processed": processed_count,
        "errors": error_count,
        "skipped": len(all_files) - len(files_to_process),
        **total_stats,
    }


@dg.job(description="Ingest all metagraph snapshots from JSONL to Django models")
def ingest_metagraph_job() -> None:
    """Job to ingest all metagraph snapshots to Django models."""
    ingest_metagraph()


@dg.sensor(job=ingest_metagraph_job, minimum_interval_seconds=60)
def metagraph_sensor(
    context: dg.SensorEvaluationContext,
    jsonl_reader: JsonLinesReader,
) -> Generator[dg.RunRequest | dg.SkipReason, None, None]:
    """Sensor to detect new metagraph files and trigger ingestion."""
    # Check if there's already a run in progress for this job
    in_progress_runs = context.instance.get_runs(
        filters=dg.RunsFilter(
            job_name=ingest_metagraph_job.name,
            statuses=[
                dg.DagsterRunStatus.STARTED,
                dg.DagsterRunStatus.QUEUED,
                dg.DagsterRunStatus.STARTING,
            ],
        ),
        limit=1,
    )

    if in_progress_runs:
        yield dg.SkipReason("Previous metagraph run still in progress")
        return

    # Use file size for efficient change detection (avoids listing all files every minute)
    current_size = jsonl_reader.get_metagraph_total_size()
    last_cursor = int(context.cursor) if context.cursor else 0

    if current_size < last_cursor:
        context.log.warning(
            "Metagraph data size decreased (cursor=%d -> current=%d). Resetting cursor and triggering re-ingest.",
            last_cursor,
            current_size,
        )
        context.update_cursor(str(current_size))
        yield dg.RunRequest()
        return

    if current_size > last_cursor:
        context.log.info("Detected new metagraph data (size: %d -> %d bytes)", last_cursor, current_size)
        yield dg.RunRequest(run_key=f"metagraph-{current_size}")
        context.update_cursor(str(current_size))


@dg.schedule(job=ingest_metagraph_job, cron_schedule="0 * * * *")
def hourly_metagraph_schedule():
    """Hourly backup schedule to ensure all metagraph records are ingested."""
    return {}
