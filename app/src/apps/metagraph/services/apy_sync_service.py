"""Service for syncing minimal metagraph data required for APY calculations.

Uses native bittensor SDK instead of sentinel SDK for simpler, faster historical sync.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import structlog
from django.db import transaction
from django.utils import timezone

from apps.metagraph.models import (
    Block,
    Coldkey,
    Hotkey,
    MechanismMetrics,
    MetagraphDump,
    Neuron,
    NeuronSnapshot,
    Subnet,
)

logger = structlog.get_logger()

# Conversion factor from TAO to rao (1 TAO = 10^9 rao)
TAO_TO_RAO = 10**9


@dataclass
class DumpMetadata:
    """Metadata for metagraph dump tracking."""

    netuid: int
    epoch_position: str  # "start", "inside", "end"
    started_at: datetime
    finished_at: datetime


def _to_rao(tao_value: float | None) -> int:
    """Convert TAO value to rao (integer)."""
    if tao_value is None:
        return 0
    return int(Decimal(str(tao_value)) * TAO_TO_RAO)


class APYSyncService:
    """
    Sync service optimized for APY calculations.

    Only syncs the minimal data required:
    - Block (number, timestamp)
    - Subnet (netuid, name)
    - Neuron (hotkey, coldkey, subnet)
    - NeuronSnapshot (emissions, total_stake, is_validator)
    - MechanismMetrics (dividend, incentive)

    Skips: weights, bonds, collaterals, evm_keys
    """

    def __init__(self) -> None:
        self._coldkey_cache: dict[str, Coldkey] = {}
        self._hotkey_cache: dict[str, Hotkey] = {}
        self._neuron_cache: dict[tuple[int, int], Neuron] = {}  # (hotkey_id, subnet_netuid)
        self._hotkeys_to_update: set[int] = set()

    def sync_metagraph(
        self,
        metagraph,  # bittensor.Metagraph
        block_number: int,
        block_timestamp: datetime | None,
        dump_metadata: DumpMetadata,
    ) -> dict[str, int]:
        """
        Sync a bittensor metagraph to Django models.

        Args:
            metagraph: Native bittensor Metagraph object
            block_number: Block number for this snapshot
            block_timestamp: Timestamp of the block (if available)
            dump_metadata: Metadata for tracking the dump

        Returns:
            Dict with counts of created/updated records
        """
        stats = {
            "coldkeys": 0,
            "hotkeys": 0,
            "neurons": 0,
            "snapshots": 0,
            "mechanism_metrics": 0,
        }

        netuid = metagraph.netuid

        with transaction.atomic():
            # 1. Sync block
            block = self._sync_block(block_number, block_timestamp, dump_metadata)

            # 2. Sync subnet
            subnet = self._sync_subnet(netuid)

            # 3. Sync neurons and snapshots
            n_neurons = metagraph.n.item() if hasattr(metagraph.n, "item") else len(metagraph.uids)

            for i in range(n_neurons):
                uid = int(metagraph.uids[i])
                hotkey_str = str(metagraph.hotkeys[i])
                coldkey_str = str(metagraph.coldkeys[i])

                # Get stake and emission values
                stake = float(metagraph.stake[i])
                emission = float(metagraph.emission[i])

                # Determine if validator (has validator_permit)
                is_validator = (
                    bool(metagraph.validator_permit[i]) if hasattr(metagraph, "validator_permit") else stake > 0
                )

                # Skip non-validators - we only need validator data for APY calculation
                if not is_validator:
                    continue

                # Get other neuron attributes
                trust = float(metagraph.trust[i]) if hasattr(metagraph, "trust") else 0.0
                rank = float(metagraph.ranks[i]) if hasattr(metagraph, "ranks") else 0.0
                is_active = bool(metagraph.active[i]) if hasattr(metagraph, "active") else True

                # Get dividend and incentive for APY calculation
                dividend = float(metagraph.dividends[i]) if hasattr(metagraph, "dividends") else 0.0
                incentive = float(metagraph.incentive[i]) if hasattr(metagraph, "incentive") else 0.0

                # Sync coldkey/hotkey
                self._get_or_create_coldkey(coldkey_str)
                stats["coldkeys"] += 1

                hotkey = self._get_or_create_hotkey(hotkey_str, coldkey_str)
                stats["hotkeys"] += 1

                # Sync neuron
                neuron = self._sync_neuron(hotkey, subnet, uid)
                stats["neurons"] += 1

                # Sync snapshot
                snapshot = self._sync_neuron_snapshot(
                    neuron=neuron,
                    block=block,
                    uid=uid,
                    total_stake=stake,
                    emissions=emission,
                    is_validator=is_validator,
                    trust=trust,
                    rank=rank,
                    is_active=is_active,
                )
                stats["snapshots"] += 1

                # Sync mechanism metrics (dividend, incentive)
                if dividend > 0 or incentive > 0:
                    self._sync_mechanism_metrics(snapshot, dividend=dividend, incentive=incentive)
                    stats["mechanism_metrics"] += 1

            # 4. Sync dump record
            self._sync_metagraph_dump(dump_metadata, block, subnet)

            # 5. Bulk update last_seen for hotkeys
            self._flush_hotkey_last_seen()

        return stats

    def _get_or_create_coldkey(self, coldkey_address: str) -> Coldkey:
        """Get or create a Coldkey, using cache."""
        if coldkey_address in self._coldkey_cache:
            return self._coldkey_cache[coldkey_address]

        coldkey, _ = Coldkey.objects.get_or_create(coldkey=coldkey_address)
        self._coldkey_cache[coldkey_address] = coldkey
        return coldkey

    def _get_or_create_hotkey(self, hotkey_address: str, coldkey_address: str) -> Hotkey:
        """Get or create a Hotkey, using cache."""
        if hotkey_address in self._hotkey_cache:
            hotkey = self._hotkey_cache[hotkey_address]
            self._hotkeys_to_update.add(hotkey.id)
            return hotkey

        coldkey = self._get_or_create_coldkey(coldkey_address)

        hotkey, created = Hotkey.objects.get_or_create(
            hotkey=hotkey_address,
            defaults={"coldkey": coldkey, "last_seen": timezone.now()},
        )
        if not created:
            if hotkey.coldkey_id != coldkey.id:
                hotkey.coldkey = coldkey
                hotkey.save(update_fields=["coldkey"])
            self._hotkeys_to_update.add(hotkey.id)

        self._hotkey_cache[hotkey_address] = hotkey
        return hotkey

    def _flush_hotkey_last_seen(self) -> int:
        """Bulk update last_seen for all hotkeys touched during this sync."""
        if not self._hotkeys_to_update:
            return 0

        now = timezone.now()
        count = Hotkey.objects.filter(id__in=self._hotkeys_to_update).update(last_seen=now)
        self._hotkeys_to_update.clear()
        return count

    def _sync_block(
        self,
        block_number: int,
        block_timestamp: datetime | None,
        dump_metadata: DumpMetadata,
    ) -> Block:
        """Sync a Block record."""
        block, created = Block.objects.get_or_create(
            number=block_number,
            defaults={
                "timestamp": block_timestamp,
                "dump_started_at": dump_metadata.started_at,
                "dump_finished_at": dump_metadata.finished_at,
            },
        )

        if not created:
            update_fields = []
            if block_timestamp and not block.timestamp:
                block.timestamp = block_timestamp
                update_fields.append("timestamp")
            if dump_metadata.started_at and not block.dump_started_at:
                block.dump_started_at = dump_metadata.started_at
                update_fields.append("dump_started_at")
            if dump_metadata.finished_at and not block.dump_finished_at:
                block.dump_finished_at = dump_metadata.finished_at
                update_fields.append("dump_finished_at")
            if update_fields:
                block.save(update_fields=update_fields)

        return block

    def _sync_subnet(self, netuid: int) -> Subnet:
        """Sync a Subnet record."""
        subnet, _ = Subnet.objects.get_or_create(
            netuid=netuid,
            defaults={"name": f"Subnet {netuid}"},
        )
        return subnet

    def _sync_neuron(self, hotkey: Hotkey, subnet: Subnet, uid: int) -> Neuron:
        """Sync a Neuron record."""
        cache_key = (hotkey.id, subnet.netuid)
        if cache_key in self._neuron_cache:
            return self._neuron_cache[cache_key]

        neuron, _ = Neuron.objects.get_or_create(
            hotkey=hotkey,
            subnet=subnet,
            defaults={"uid": uid},
        )

        if neuron.uid != uid:
            neuron.uid = uid
            neuron.save(update_fields=["uid"])

        self._neuron_cache[cache_key] = neuron
        return neuron

    def _sync_neuron_snapshot(
        self,
        neuron: Neuron,
        block: Block,
        uid: int,
        total_stake: float,
        emissions: float,
        is_validator: bool,
        trust: float = 0.0,
        rank: float = 0.0,
        is_active: bool = True,
    ) -> NeuronSnapshot:
        """Sync a NeuronSnapshot record with APY-relevant fields."""
        snapshot, _ = NeuronSnapshot.objects.update_or_create(
            neuron=neuron,
            block=block,
            defaults={
                "uid": uid,
                "total_stake": _to_rao(total_stake),
                "emissions": _to_rao(emissions),
                "is_validator": is_validator,
                "trust": trust,
                "rank": rank,
                "is_active": is_active,
                # Fields not needed for APY but required by model
                "axon_address": "",
                "normalized_stake": 0.0,
                "is_immune": False,
                "has_any_weights": False,
            },
        )
        return snapshot

    def _sync_mechanism_metrics(
        self,
        snapshot: NeuronSnapshot,
        dividend: float,
        incentive: float,
        mech_id: int = 0,
    ) -> MechanismMetrics:
        """Sync MechanismMetrics with dividend and incentive for APY calculation."""
        metrics, _ = MechanismMetrics.objects.update_or_create(
            snapshot=snapshot,
            mech_id=mech_id,
            defaults={
                "dividend": dividend,
                "incentive": incentive,
                "consensus": 0.0,
                "validator_trust": 0.0,
                "weights_sum": 0.0,
            },
        )
        return metrics

    def _sync_metagraph_dump(
        self,
        dump_metadata: DumpMetadata,
        block: Block,
        subnet: Subnet,
    ) -> MetagraphDump:
        """Sync a MetagraphDump record."""
        epoch_position_map = {"start": 0, "inside": 1, "end": 2}
        epoch_position = epoch_position_map.get(dump_metadata.epoch_position)

        dump, _ = MetagraphDump.objects.update_or_create(
            netuid=dump_metadata.netuid,
            block=block,
            defaults={
                "epoch_position": epoch_position,
                "started_at": dump_metadata.started_at,
                "finished_at": dump_metadata.finished_at,
            },
        )
        return dump
