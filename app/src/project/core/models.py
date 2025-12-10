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


class SubnetEvent(BlockchainEvent):
    netuid = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True


class HyperparamEvent(SubnetEvent):
    """
    Stores hyperparameter change events from the Bittensor blockchain.

    Each record represents a single hyperparameter change extrinsic.
    """

    call_args = models.JSONField(default=dict)

    class Meta:
        ordering = ["-block_number"]
        indexes = [
            models.Index(fields=["block_number", "netuid"]),
            models.Index(fields=["netuid", "address"]),
        ]

    def __str__(self) -> str:
        return f"hyperparam change netuid={self.netuid} @ block {self.block_number}"


class SetWeightsEvent(SubnetEvent):
    """
    Stores set_weights extrinsic events from the Bittensor blockchain.

    Each record represents a single set_weights call.
    """

    weights_data = models.JSONField(default=dict)
    events = models.JSONField(default=list)

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
