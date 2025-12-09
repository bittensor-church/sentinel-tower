"""Django models for blockchain data storage."""

from django.db import models


class HyperparamEvent(models.Model):
    """
    Stores hyperparameter change events from the Bittensor blockchain.

    Each record represents a single hyperparameter change extrinsic.
    """

    block_number = models.PositiveBigIntegerField(db_index=True)
    extrinsic_hash = models.CharField(max_length=66, unique=True)

    # Call information
    call_function = models.CharField(max_length=100, db_index=True)
    call_module = models.CharField(max_length=100)

    # Network/subnet info
    netuid = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    # Signer
    address = models.CharField(max_length=66, null=True, blank=True, db_index=True)

    # Status
    status = models.CharField(max_length=20, null=True, blank=True)

    # Store full call args as JSON for flexibility
    call_args = models.JSONField(default=dict)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-block_number"]
        indexes = [
            models.Index(fields=["block_number", "netuid"]),
            models.Index(fields=["call_function", "netuid"]),
        ]

    def __str__(self) -> str:
        netuid_str = f" (netuid={self.netuid})" if self.netuid is not None else ""
        return f"{self.call_function}{netuid_str} @ block {self.block_number}"


class SetWeightsEvent(models.Model):
    """
    Stores set_weights extrinsic events from the Bittensor blockchain.

    Each record represents a single set_weights call.
    """

    block_number = models.PositiveBigIntegerField(db_index=True)
    extrinsic_hash = models.CharField(max_length=66, unique=True)

    # Network/subnet info
    netuid = models.PositiveIntegerField(db_index=True)

    # Signer (validator hotkey)
    address = models.CharField(max_length=66, null=True, blank=True, db_index=True)

    # Status
    status = models.CharField(max_length=20, null=True, blank=True)

    # Store weights data as JSON
    weights_data = models.JSONField(default=dict)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-block_number"]
        indexes = [
            models.Index(fields=["block_number", "netuid"]),
            models.Index(fields=["netuid", "address"]),
        ]

    def __str__(self) -> str:
        return f"set_weights netuid={self.netuid} @ block {self.block_number}"


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
