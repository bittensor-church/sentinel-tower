"""Django models for extrinsic data storage."""

from django.db import models


class Extrinsic(models.Model):
    """
    Generic extrinsic storage matching bittensor SDK BlockInfo.extrinsics structure.

    Captures full extrinsic data from the blockchain including call arguments,
    signature data, events, and execution status.
    """

    # Block context
    block_number = models.PositiveBigIntegerField(db_index=True)
    block_hash = models.CharField(max_length=66, blank=True, db_index=True)
    extrinsic_hash = models.CharField(max_length=66, unique=True)
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

    # Call data
    call_module = models.CharField(max_length=100)
    call_function = models.CharField(max_length=100, db_index=True)
    call_args = models.JSONField(
        default=dict,
        help_text="Call arguments from extrinsic",
    )

    # Address and signature
    address = models.CharField(max_length=66, blank=True, db_index=True)
    signature = models.JSONField(null=True, blank=True)
    nonce = models.PositiveBigIntegerField(null=True, blank=True)
    tip_rao = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Tip in rao",
    )

    # Execution result
    status = models.CharField(max_length=20, blank=True)
    success = models.BooleanField(default=False, db_index=True)
    error_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Error attributes if failed",
    )

    # Events triggered by this extrinsic
    events = models.JSONField(
        default=list,
        help_text="Events associated with this extrinsic",
    )

    # Optional subnet context (for subnet-related extrinsics)
    netuid = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "extrinsics"
        ordering = ["-block_number", "-extrinsic_index"]
        indexes = [
            models.Index(fields=["block_number", "extrinsic_index"]),
            models.Index(fields=["block_hash"]),
            models.Index(fields=["address", "block_number"]),
            models.Index(fields=["call_module", "call_function", "success"]),
            models.Index(fields=["netuid", "call_function"]),
            models.Index(fields=["block_number", "call_function"]),
            models.Index(fields=["address", "call_function"]),
        ]

    def __str__(self) -> str:
        status = "+" if self.success else "-"
        return f"{self.call_module}.{self.call_function} {status} @ {self.block_number}:{self.extrinsic_index}"
