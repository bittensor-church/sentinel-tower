"""Django models for extrinsic data storage."""

from django.db import models


class SubnetHyperparam(models.Model):
    """
    Tracks current hyperparam values for each subnet.

    Used to show "old → new" values in notifications when hyperparams change.
    """

    netuid = models.PositiveIntegerField(db_index=True)
    param_name = models.CharField(max_length=100, db_index=True)
    value = models.JSONField(help_text="Current value of the hyperparam")
    last_block_number = models.PositiveBigIntegerField(help_text="Block number when this value was last set")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "subnet_hyperparams"
        unique_together = [["netuid", "param_name"]]
        indexes = [
            models.Index(fields=["netuid", "param_name"]),
        ]

    def __str__(self) -> str:
        return f"Subnet {self.netuid}: {self.param_name} = {self.value}"


class SubnetHyperparamHistory(models.Model):
    """
    Tracks hyperparam value changes over time for each subnet.

    Used for Grafana dashboards to display how values changed over time.
    """

    netuid = models.PositiveIntegerField(db_index=True)
    param_name = models.CharField(max_length=100, db_index=True)
    old_value = models.JSONField(
        null=True,
        blank=True,
        help_text="Previous value before change (null if first recorded value)",
    )
    new_value = models.JSONField(help_text="New value after change")
    block_number = models.PositiveBigIntegerField(db_index=True)
    extrinsic_hash = models.CharField(max_length=66, blank=True, db_index=True)
    address = models.CharField(
        max_length=66,
        blank=True,
        help_text="Address that made the change",
    )
    success = models.BooleanField(
        default=True,
        help_text="Whether the extrinsic succeeded",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "subnet_hyperparam_history"
        ordering = ["-block_number"]
        indexes = [
            models.Index(fields=["netuid", "param_name", "block_number"]),
            models.Index(fields=["netuid", "created_at"]),
            models.Index(fields=["param_name", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Subnet {self.netuid}: {self.param_name} {self.old_value} → {self.new_value} @ {self.block_number}"


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
