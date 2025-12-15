"""Django models for blockchain data storage."""

from django.db import models


class BlockchainEvent(models.Model):
    block_number = models.PositiveBigIntegerField(db_index=True)
    extrinsic_hash = models.CharField(max_length=66, unique=True)
    address = models.CharField(max_length=66, blank=True, db_index=True)
    status = models.CharField(max_length=20, blank=True)

    call_function = models.CharField(max_length=100, db_index=True)
    call_module = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["-block_number"]
        indexes = [
            models.Index(fields=["block_number", "call_function"]),
            models.Index(fields=["address", "call_function"]),
        ]


class Extrinsic(BlockchainEvent):
    """
    Generic extrinsic storage matching bittensor SDK BlockInfo.extrinsics structure.

    Captures full extrinsic data from the blockchain including call arguments,
    signature data, events, and execution status.
    """

    # Block context
    block_hash = models.CharField(max_length=66, blank=True, db_index=True)
    extrinsic_index = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Index within the block",
    )
    block_timestamp = models.PositiveBigIntegerField(
        null=True,
        blank=True,
        help_text="Block timestamp from Timestamp.Now",
    )

    # Execution result
    success = models.BooleanField(default=False, db_index=True)
    error_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Error attributes if failed",
    )

    # Call data from ext.value_serialized
    call_args = models.JSONField(
        default=dict,
        help_text="Call arguments from extrinsic",
    )

    # Signature data
    signature = models.JSONField(null=True, blank=True)
    nonce = models.PositiveBigIntegerField(null=True, blank=True)
    tip_rao = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Tip in rao",
    )

    # Events triggered by this extrinsic
    events = models.JSONField(
        default=list,
        help_text="Events associated with this extrinsic",
    )

    # Optional subnet context (for subnet-related extrinsics)
    netuid = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "extrinsics"
        ordering = ["-block_number", "-extrinsic_index"]
        indexes = [
            models.Index(fields=["block_number", "extrinsic_index"]),
            models.Index(fields=["block_hash"]),
            models.Index(fields=["address", "block_number"]),
            models.Index(fields=["call_module", "call_function", "success"]),
            models.Index(fields=["netuid", "call_function"]),
        ]

    def __str__(self) -> str:
        status = "+" if self.success else "-"
        return f"{self.call_module}.{self.call_function} {status} @ {self.block_number}:{self.extrinsic_index}"

    @classmethod
    def from_block_info(
        cls,
        block_info: "BlockInfo",  # noqa: F821
        extrinsics_with_events: dict[int, list[dict]],
    ) -> list["Extrinsic"]:
        """
        Create Extrinsic instances from bittensor SDK BlockInfo.

        Args:
            block_info: BlockInfo from Subtensor.get_block_info()
            extrinsics_with_events: Events grouped by extrinsic index

        Returns:
            List of Extrinsic model instances (not saved)

        """
        instances = []

        for idx, ext in enumerate(block_info.extrinsics):
            serialized = ext.value_serialized
            call = serialized.get("call", {})
            events = extrinsics_with_events.get(idx, [])

            # Determine success from events
            success = False
            error_data = None
            for event in events:
                if event.get("module_id") == "System":
                    if event.get("event_id") == "ExtrinsicSuccess":
                        success = True
                    elif event.get("event_id") == "ExtrinsicFailed":
                        error_data = event.get("attributes")

            # Extract netuid from call_args if present
            netuid = None
            for arg in call.get("call_args", []):
                if arg.get("name") == "netuid":
                    netuid = arg.get("value")
                    break

            instance = cls(
                block_number=block_info.number,
                block_hash=block_info.hash,
                block_timestamp=block_info.timestamp,
                extrinsic_index=idx,
                extrinsic_hash=getattr(ext, "extrinsic_hash", None) or "",
                call_module=call.get("call_module", ""),
                call_function=call.get("call_function", ""),
                call_args=call.get("call_args", []),
                address=serialized.get("address") or "",
                signature=serialized.get("signature"),
                nonce=serialized.get("nonce"),
                tip_rao=serialized.get("tip"),
                success=success,
                error_data=error_data,
                events=events,
                netuid=netuid,
                status="Success" if success else "Failed" if error_data else "Unknown",
            )
            instances.append(instance)

        return instances


class IngestionCheckpoint(models.Model):
    """
    Tracks the last processed line number for each JSONL file.

    This allows incremental processing of new records.
    """

    file_path = models.CharField(max_length=255, unique=True)
    last_processed_line = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.file_path}: line {self.last_processed_line}"
