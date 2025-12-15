"""Django models for metagraph data storage."""

from django.db import models
from django.db.models import Q


class Coldkey(models.Model):
    """Coldkey wallet addresses."""

    coldkey = models.CharField(max_length=66, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metagraph_coldkey"

    def __str__(self) -> str:
        return self.coldkey


class Hotkey(models.Model):
    """Hotkey wallet addresses linked to coldkeys."""

    hotkey = models.CharField(max_length=66, unique=True)
    coldkey = models.ForeignKey(
        Coldkey,
        on_delete=models.CASCADE,
        related_name="hotkeys",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_hotkey"

    def __str__(self) -> str:
        return self.hotkey


class EvmKey(models.Model):
    """EVM addresses associated with neurons."""

    evm_address = models.CharField(max_length=42, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metagraph_evm_key"

    def __str__(self) -> str:
        return self.evm_address


class Block(models.Model):
    """Block information for metagraph snapshots."""

    number = models.PositiveBigIntegerField(primary_key=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    dump_started_at = models.DateTimeField(null=True, blank=True)
    dump_finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_block"

    def __str__(self) -> str:
        return f"Block {self.number}"


class Subnet(models.Model):
    """Subnet information."""

    netuid = models.PositiveIntegerField(primary_key=True)
    name = models.CharField(max_length=255, blank=True)
    owner_hotkey = models.ForeignKey(
        Hotkey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owned_subnets",
    )
    registered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_subnet"

    def __str__(self) -> str:
        return f"Subnet {self.netuid}: {self.name}"


class Neuron(models.Model):
    """Neuron representing a hotkey registered on a subnet."""

    hotkey = models.ForeignKey(
        Hotkey,
        on_delete=models.CASCADE,
        related_name="neurons",
    )
    subnet = models.ForeignKey(
        Subnet,
        on_delete=models.CASCADE,
        related_name="neurons",
    )
    uid = models.PositiveIntegerField()
    evm_key = models.ForeignKey(
        EvmKey,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="neurons",
    )
    first_seen_block = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_neuron"
        constraints = [
            models.UniqueConstraint(
                fields=["hotkey", "subnet"],
                name="unique_hotkey_subnet",
            ),
        ]
        indexes = [
            models.Index(fields=["subnet", "uid"]),
        ]

    def __str__(self) -> str:
        return f"Neuron {self.uid} on subnet {self.subnet.pk}"


class NeuronSnapshot(models.Model):
    """Point-in-time snapshot of neuron state at a specific block."""

    neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="neuron_snapshots",
    )
    uid = models.PositiveIntegerField()
    axon_address = models.CharField(max_length=255, blank=True)
    total_stake = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        default=0,
        help_text="Total stake in rao",
    )
    normalized_stake = models.FloatField(default=0.0)
    rank = models.FloatField(default=0.0)
    trust = models.FloatField(default=0.0)
    emissions = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        default=0,
        help_text="Emissions in rao",
    )
    is_active = models.BooleanField(default=False)
    is_validator = models.BooleanField(default=False)
    is_immune = models.BooleanField(default=False)
    has_any_weights = models.BooleanField(default=False)
    neuron_version = models.PositiveIntegerField(null=True, blank=True)
    block_at_registration = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_neuron_snapshot"
        constraints = [
            models.UniqueConstraint(
                fields=["neuron", "block"],
                name="unique_neuron_block",
            ),
        ]
        indexes = [
            models.Index(fields=["block"]),
            models.Index(
                fields=["block", "neuron"],
                condition=Q(is_validator=True),
                name="idx_validator_snapshots",
            ),
        ]

    def __str__(self) -> str:
        return f"Snapshot of neuron {self.neuron.pk} at block {self.block.pk}"


class MechanismMetrics(models.Model):
    """Per-mechanism metrics for a neuron snapshot."""

    snapshot = models.ForeignKey(
        NeuronSnapshot,
        on_delete=models.CASCADE,
        related_name="mechanism_metrics",
    )
    mech_id = models.PositiveIntegerField()
    incentive = models.FloatField(default=0.0)
    dividend = models.FloatField(default=0.0)
    consensus = models.FloatField(default=0.0)
    validator_trust = models.FloatField(default=0.0)
    weights_sum = models.FloatField(default=0.0)
    last_update = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_mechanism_metrics"
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "mech_id"],
                name="unique_snapshot_mech",
            ),
        ]
        indexes = [
            models.Index(fields=["snapshot"]),
        ]

    def __str__(self) -> str:
        return f"Mech {self.mech_id} metrics for snapshot {self.snapshot.pk}"


class Weight(models.Model):
    """Weight set by a validator neuron on another neuron."""

    source_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="outgoing_weights",
    )
    target_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="incoming_weights",
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="weights",
    )
    mech_id = models.PositiveIntegerField()
    weight = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metagraph_weight"
        constraints = [
            models.UniqueConstraint(
                fields=["source_neuron", "target_neuron", "block", "mech_id"],
                name="unique_weight",
            ),
        ]
        indexes = [
            models.Index(fields=["block", "source_neuron"]),
            models.Index(fields=["block", "target_neuron"]),
        ]

    def __str__(self) -> str:
        return f"Weight {self.weight} from {self.source_neuron.pk} to {self.target_neuron.pk}"


class Bond(models.Model):
    """Bond between neurons."""

    source_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="outgoing_bonds",
    )
    target_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="incoming_bonds",
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="bonds",
    )
    mech_id = models.PositiveIntegerField()
    bond = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metagraph_bond"
        constraints = [
            models.UniqueConstraint(
                fields=["source_neuron", "target_neuron", "block", "mech_id"],
                name="unique_bond",
            ),
        ]
        indexes = [
            models.Index(fields=["block", "source_neuron"]),
            models.Index(fields=["block", "target_neuron"]),
        ]

    def __str__(self) -> str:
        return f"Bond {self.bond} from {self.source_neuron.pk} to {self.target_neuron.pk}"


class Collateral(models.Model):
    """Collateral between neurons."""

    source_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="outgoing_collateral",
    )
    target_neuron = models.ForeignKey(
        Neuron,
        on_delete=models.CASCADE,
        related_name="incoming_collateral",
    )
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="collaterals",
    )
    amount = models.DecimalField(
        max_digits=30,
        decimal_places=0,
        help_text="Collateral amount in rao",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "metagraph_collateral"
        constraints = [
            models.UniqueConstraint(
                fields=["source_neuron", "target_neuron", "block"],
                name="unique_collateral",
            ),
        ]
        indexes = [
            models.Index(fields=["source_neuron", "block"]),
            models.Index(fields=["target_neuron", "block"]),
        ]

    def __str__(self) -> str:
        return f"Collateral {self.amount} from {self.source_neuron.pk} to {self.target_neuron.pk}"


class MetagraphDump(models.Model):
    """Record of metagraph dump operations."""

    netuid = models.PositiveIntegerField()
    block = models.ForeignKey(
        Block,
        on_delete=models.CASCADE,
        related_name="metagraph_dumps",
    )
    epoch_position = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metagraph_dump"
        constraints = [
            models.UniqueConstraint(
                fields=["netuid", "block"],
                name="unique_metagraph_dump",
            ),
        ]

    def __str__(self) -> str:
        return f"Dump for subnet {self.netuid} at block {self.block.pk}"
