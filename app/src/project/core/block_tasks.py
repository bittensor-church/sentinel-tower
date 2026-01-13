from datetime import UTC, datetime

import structlog
from abstract_block_dumper.v1.decorators import block_task
from sentinel.v1.dto import ExtrinsicDTO
from sentinel.v1.services.sentinel import sentinel_service

from project.core.models import Extrinsic
from project.core.notifications import send_discord_notification
from project.core.services import JsonLinesStorage
from project.core.utils import get_provider_for_block

logger = structlog.get_logger()


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
    """Parse an extrinsic record into Extrinsic model fields."""
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


# @block_task(celery_kwargs={"rate_limit": "10/m"})
def store_block_extrinsics(block_number: int) -> str:
    """
    Store extrinsics from the given block number.

    Fetches extrinsics from the blockchain, stores them as JSONL artifacts,
    and syncs them to Django models.
    """
    with get_provider_for_block(block_number) as provider:
        service = sentinel_service(provider)
        block = service.ingest_block(block_number)
        extrinsics = block.extrinsics
        timestamp = block.timestamp

    if not extrinsics:
        logger.info("No extrinsics found in block", block_number=block_number)
        return ""

    # Store to JSONL artifact
    artifact_count = store_extrinsics_artifact(extrinsics, block_number, timestamp)

    # Sync to Django models
    db_count = sync_extrinsics_to_db(extrinsics, block_number, timestamp)

    logger.info(
        "Stored and synced extrinsics",
        block_number=block_number,
        artifact_count=artifact_count,
        db_count=db_count,
    )

    return f"Block {block_number}: stored {artifact_count} artifacts, synced {db_count} to DB."


def store_extrinsics_artifact(extrinsics: list[ExtrinsicDTO], block_number: int, timestamp: int | None) -> int:
    """Store extrinsics to JSONL artifact files."""
    extrinsics_storage = JsonLinesStorage("data/bittensor/extrinsics/{date}.jsonl")
    if not extrinsics:
        return 0

    # Convert timestamp to date string for partitioning (timestamp is in milliseconds)
    date_str = datetime.fromtimestamp(timestamp / 1000, tz=UTC).strftime("%Y-%m-%d") if timestamp else "unknown"

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


def sync_extrinsics_to_db(extrinsics: list[ExtrinsicDTO], block_number: int, timestamp: int | None) -> int:
    """Sync extrinsics to Django Extrinsic model."""
    if not extrinsics:
        return 0

    # Build records for database
    records_to_create = []
    existing_hashes = set(
        Extrinsic.objects.filter(block_number=block_number).values_list("extrinsic_hash", flat=True),
    )

    for extrinsic in extrinsics:
        record = {
            "block_number": block_number,
            "timestamp": timestamp,
            **extrinsic.model_dump(),
        }
        parsed = _parse_extrinsic_record(record)
        if not parsed:
            continue

        # Skip if already exists
        if parsed["extrinsic_hash"] in existing_hashes:
            continue

        # Send Discord notification for matching extrinsics (new only)
        send_discord_notification(parsed)

        records_to_create.append(Extrinsic(**parsed))

    if records_to_create:
        Extrinsic.objects.bulk_create(records_to_create, ignore_conflicts=True)

    return len(records_to_create)
