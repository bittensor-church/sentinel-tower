"""Service for syncing metagraph JSONL data to Django models."""

from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from django.db import transaction
from django.utils import timezone

from apps.metagraph.models import (
    Block,
    Bond,
    Coldkey,
    Collateral,
    EvmKey,
    Hotkey,
    MechanismMetrics,
    MetagraphDump,
    Neuron,
    NeuronSnapshot,
    Subnet,
    Weight,
)

logger = structlog.get_logger()

# Conversion factor from TAO to rao (1 TAO = 10^9 rao)
TAO_TO_RAO = 10**9


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string to datetime object."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)
        return dt
    except (ValueError, TypeError):
        return None


def _to_rao(tao_value: float | str | None) -> int:
    """Convert TAO value to rao (integer)."""
    if tao_value is None:
        return 0
    return int(Decimal(str(tao_value)) * TAO_TO_RAO)


class MetagraphSyncService:
    """Service to sync metagraph snapshot data from JSONL to Django models."""

    def __init__(self) -> None:
        # Caches for bulk operations within a single sync
        self._coldkey_cache: dict[str, Coldkey] = {}
        self._hotkey_cache: dict[str, Hotkey] = {}
        self._evmkey_cache: dict[str, EvmKey] = {}
        self._neuron_cache: dict[tuple[int, int], Neuron] = {}  # (hotkey_id, subnet_netuid)

    def sync_metagraph(self, data: dict[str, Any]) -> dict[str, int]:
        """
        Sync a full metagraph snapshot to Django models.

        Args:
            data: Deserialized FullSubnetSnapshot data

        Returns:
            Dict with counts of created/updated records

        """
        stats = {
            "coldkeys": 0,
            "hotkeys": 0,
            "evmkeys": 0,
            "subnets": 0,
            "blocks": 0,
            "neurons": 0,
            "snapshots": 0,
            "mechanism_metrics": 0,
            "weights": 0,
            "bonds": 0,
            "collaterals": 0,
            "dumps": 0,
        }

        with transaction.atomic():
            # 1. Sync block (pass dump data for timestamps)
            dump_data = data.get("dump") or {}
            block = self._sync_block(data["block"], dump_data)
            stats["blocks"] = 1

            # 2. Sync subnet (and owner hotkey/coldkey if present)
            subnet_data = data["subnet"]
            subnet = self._sync_subnet(subnet_data)
            stats["subnets"] = 1

            # 3. Sync neurons and their snapshots
            neurons_data = data.get("neurons", [])
            for neuron_data in neurons_data:
                # Sync hotkey/coldkey
                neuron_rel = neuron_data.get("neuron", {})
                hotkey_data = neuron_rel.get("hotkey", {})
                if hotkey_data:
                    coldkey_data = hotkey_data.get("coldkey")
                    if coldkey_data:
                        self._get_or_create_coldkey(coldkey_data["coldkey"])
                        stats["coldkeys"] += 1
                    self._get_or_create_hotkey(hotkey_data["hotkey"], coldkey_data)
                    stats["hotkeys"] += 1

                # Sync EVM key if present
                evm_key_data = neuron_rel.get("evm_key")
                if evm_key_data:
                    self._get_or_create_evmkey(evm_key_data["evm_address"])
                    stats["evmkeys"] += 1

                # Sync neuron
                neuron = self._sync_neuron(neuron_rel, subnet)
                stats["neurons"] += 1

                # Sync neuron snapshot
                snapshot = self._sync_neuron_snapshot(neuron_data, neuron, block)
                stats["snapshots"] += 1

                # Sync mechanism metrics
                mechanisms = neuron_data.get("mechanisms", [])
                for mech_data in mechanisms:
                    self._sync_mechanism_metrics(mech_data, snapshot)
                    stats["mechanism_metrics"] += 1

            # 4. Sync weights (if present)
            weights_data = data.get("weights") or []
            if weights_data:
                stats["weights"] = self._sync_weights(weights_data, block, subnet)

            # 5. Sync bonds (if present)
            bonds_data = data.get("bonds") or []
            if bonds_data:
                stats["bonds"] = self._sync_bonds(bonds_data, block, subnet)

            # 6. Sync collaterals (if present)
            collaterals_data = data.get("collaterals") or []
            if collaterals_data:
                stats["collaterals"] = self._sync_collaterals(collaterals_data, block, subnet)

            # 7. Sync metagraph dump record (always create one to track what's been synced)
            # dump_data was already extracted above for block timestamps
            self._sync_metagraph_dump(dump_data, block, subnet)
            stats["dumps"] = 1

        return stats

    def _get_or_create_coldkey(self, coldkey_address: str) -> Coldkey:
        """Get or create a Coldkey, using cache."""
        if coldkey_address in self._coldkey_cache:
            return self._coldkey_cache[coldkey_address]

        coldkey, _ = Coldkey.objects.get_or_create(coldkey=coldkey_address)
        self._coldkey_cache[coldkey_address] = coldkey
        return coldkey

    def _get_or_create_hotkey(
        self,
        hotkey_address: str,
        coldkey_data: dict[str, Any] | None,
    ) -> Hotkey:
        """Get or create a Hotkey, using cache."""
        if hotkey_address in self._hotkey_cache:
            hotkey = self._hotkey_cache[hotkey_address]
            # Update last_seen
            hotkey.last_seen = timezone.now()
            hotkey.save(update_fields=["last_seen"])
            return hotkey

        coldkey = None
        if coldkey_data:
            coldkey = self._get_or_create_coldkey(coldkey_data["coldkey"])

        hotkey, created = Hotkey.objects.get_or_create(
            hotkey=hotkey_address,
            defaults={"coldkey": coldkey, "last_seen": timezone.now()},
        )
        if not created:
            hotkey.last_seen = timezone.now()
            if coldkey and hotkey.coldkey_id != coldkey.id:
                hotkey.coldkey = coldkey
            hotkey.save(update_fields=["last_seen", "coldkey"])

        self._hotkey_cache[hotkey_address] = hotkey
        return hotkey

    def _get_or_create_evmkey(self, evm_address: str) -> EvmKey:
        """Get or create an EvmKey, using cache."""
        if evm_address in self._evmkey_cache:
            return self._evmkey_cache[evm_address]

        evmkey, _ = EvmKey.objects.get_or_create(evm_address=evm_address)
        self._evmkey_cache[evm_address] = evmkey
        return evmkey

    def _sync_block(self, block_data: dict[str, Any], dump_data: dict[str, Any] | None = None) -> Block:
        """Sync a Block record."""
        block_number = block_data["block_number"]
        timestamp = _parse_datetime(block_data.get("timestamp"))

        # Extract dump timestamps if available
        dump_started_at = None
        dump_finished_at = None
        if dump_data:
            dump_started_at = _parse_datetime(dump_data.get("started_at"))
            dump_finished_at = _parse_datetime(dump_data.get("finished_at"))

        block, created = Block.objects.get_or_create(
            number=block_number,
            defaults={
                "timestamp": timestamp,
                "dump_started_at": dump_started_at,
                "dump_finished_at": dump_finished_at,
            },
        )

        if not created:
            # Update fields if they were missing
            update_fields = []
            if timestamp and not block.timestamp:
                block.timestamp = timestamp
                update_fields.append("timestamp")
            if dump_started_at and not block.dump_started_at:
                block.dump_started_at = dump_started_at
                update_fields.append("dump_started_at")
            if dump_finished_at and not block.dump_finished_at:
                block.dump_finished_at = dump_finished_at
                update_fields.append("dump_finished_at")
            if update_fields:
                block.save(update_fields=update_fields)

        return block

    def _sync_subnet(self, subnet_data: dict[str, Any]) -> Subnet:
        """Sync a Subnet record."""
        netuid = subnet_data["netuid"]

        # Get owner hotkey if present
        owner_hotkey = None
        owner_hotkey_data = subnet_data.get("owner_hotkey")
        if owner_hotkey_data:
            coldkey_data = owner_hotkey_data.get("coldkey")
            if coldkey_data:
                self._get_or_create_coldkey(coldkey_data["coldkey"])
            owner_hotkey = self._get_or_create_hotkey(
                owner_hotkey_data["hotkey"],
                coldkey_data,
            )

        registered_at = _parse_datetime(subnet_data.get("registered_at"))

        subnet, created = Subnet.objects.get_or_create(
            netuid=netuid,
            defaults={
                "name": subnet_data.get("name", ""),
                "owner_hotkey": owner_hotkey,
                "registered_at": registered_at,
            },
        )

        if not created:
            updated = False
            if subnet_data.get("name") and subnet.name != subnet_data["name"]:
                subnet.name = subnet_data["name"]
                updated = True
            if owner_hotkey and subnet.owner_hotkey_id != owner_hotkey.id:
                subnet.owner_hotkey = owner_hotkey
                updated = True
            if updated:
                subnet.save()

        return subnet

    def _sync_neuron(self, neuron_data: dict[str, Any], subnet: Subnet) -> Neuron:
        """Sync a Neuron record."""
        hotkey_data = neuron_data.get("hotkey", {})
        hotkey = self._hotkey_cache.get(hotkey_data.get("hotkey", ""))
        if not hotkey:
            coldkey_data = hotkey_data.get("coldkey")
            hotkey = self._get_or_create_hotkey(hotkey_data["hotkey"], coldkey_data)

        cache_key = (hotkey.id, subnet.netuid)
        if cache_key in self._neuron_cache:
            return self._neuron_cache[cache_key]

        evm_key = None
        evm_key_data = neuron_data.get("evm_key")
        if evm_key_data:
            evm_key = self._get_or_create_evmkey(evm_key_data["evm_address"])

        neuron, _ = Neuron.objects.get_or_create(
            hotkey=hotkey,
            subnet=subnet,
            defaults={
                "uid": neuron_data.get("uid", 0),
                "evm_key": evm_key,
            },
        )

        # Update uid and evm_key if changed
        updated = False
        if neuron.uid != neuron_data.get("uid", 0):
            neuron.uid = neuron_data.get("uid", 0)
            updated = True
        if evm_key and neuron.evm_key_id != evm_key.id:
            neuron.evm_key = evm_key
            updated = True
        if updated:
            neuron.save()

        self._neuron_cache[cache_key] = neuron
        return neuron

    def _sync_neuron_snapshot(
        self,
        snapshot_data: dict[str, Any],
        neuron: Neuron,
        block: Block,
    ) -> NeuronSnapshot:
        """Sync a NeuronSnapshot record."""
        snapshot, _ = NeuronSnapshot.objects.update_or_create(
            neuron=neuron,
            block=block,
            defaults={
                "uid": snapshot_data.get("uid", 0),
                "axon_address": snapshot_data.get("axon_address", ""),
                "total_stake": _to_rao(snapshot_data.get("total_stake", 0)),
                "normalized_stake": snapshot_data.get("normalized_stake", 0.0),
                "rank": snapshot_data.get("rank", 0.0),
                "trust": snapshot_data.get("trust", 0.0),
                "emissions": _to_rao(snapshot_data.get("emissions", 0)),
                "is_active": snapshot_data.get("is_active", False),
                "is_validator": snapshot_data.get("is_validator", False),
                "is_immune": snapshot_data.get("is_immune", False),
                "has_any_weights": snapshot_data.get("has_any_weights", False),
                "neuron_version": snapshot_data.get("neuron_version"),
                "block_at_registration": snapshot_data.get("block_at_registration"),
            },
        )
        return snapshot

    def _sync_mechanism_metrics(
        self,
        mech_data: dict[str, Any],
        snapshot: NeuronSnapshot,
    ) -> MechanismMetrics:
        """Sync a MechanismMetrics record."""
        metrics, _ = MechanismMetrics.objects.update_or_create(
            snapshot=snapshot,
            mech_id=mech_data.get("mech_id", 0),
            defaults={
                "incentive": mech_data.get("incentive", 0.0),
                "dividend": mech_data.get("dividend", 0.0),
                "consensus": mech_data.get("consensus", 0.0),
                "validator_trust": mech_data.get("validator_trust", 0.0),
                "weights_sum": mech_data.get("weights_sum", 0.0),
                "last_update": mech_data.get("last_update"),
            },
        )
        return metrics

    def _get_neuron_by_uid(self, uid: int, subnet: Subnet) -> Neuron | None:
        """Get neuron by UID within a subnet."""
        # First check cache
        for (hotkey_id, subnet_netuid), neuron in self._neuron_cache.items():
            if subnet_netuid == subnet.netuid and neuron.uid == uid:
                return neuron

        # Query database
        try:
            return Neuron.objects.get(subnet=subnet, uid=uid)
        except Neuron.DoesNotExist:
            return None

    def _sync_weights(
        self,
        weights_data: list[dict[str, Any]],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Weight records in bulk."""
        if not weights_data:
            return 0

        # Build UID to neuron mapping
        uid_to_neuron: dict[int, Neuron] = {}
        for (_, subnet_netuid), neuron in self._neuron_cache.items():
            if subnet_netuid == subnet.netuid:
                uid_to_neuron[neuron.uid] = neuron

        weights_to_create = []
        for w in weights_data:
            source_uid = w.get("source_neuron_uid")
            target_uid = w.get("target_neuron_uid")

            source_neuron = uid_to_neuron.get(source_uid)
            target_neuron = uid_to_neuron.get(target_uid)

            if not source_neuron or not target_neuron:
                continue

            weights_to_create.append(
                Weight(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    mech_id=w.get("mech_id", 0),
                    weight=w.get("weight", 0.0),
                ),
            )

        if weights_to_create:
            Weight.objects.bulk_create(
                weights_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(weights_to_create)

    def _sync_bonds(
        self,
        bonds_data: list[dict[str, Any]],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Bond records in bulk."""
        if not bonds_data:
            return 0

        # Build UID to neuron mapping
        uid_to_neuron: dict[int, Neuron] = {}
        for (_, subnet_netuid), neuron in self._neuron_cache.items():
            if subnet_netuid == subnet.netuid:
                uid_to_neuron[neuron.uid] = neuron

        bonds_to_create = []
        for b in bonds_data:
            source_uid = b.get("source_neuron_uid")
            target_uid = b.get("target_neuron_uid")

            source_neuron = uid_to_neuron.get(source_uid)
            target_neuron = uid_to_neuron.get(target_uid)

            if not source_neuron or not target_neuron:
                continue

            bonds_to_create.append(
                Bond(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    mech_id=b.get("mech_id", 0),
                    bond=b.get("bond", 0.0),
                ),
            )

        if bonds_to_create:
            Bond.objects.bulk_create(
                bonds_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(bonds_to_create)

    def _sync_collaterals(
        self,
        collaterals_data: list[dict[str, Any]],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Collateral records in bulk."""
        if not collaterals_data:
            return 0

        # Build UID to neuron mapping
        uid_to_neuron: dict[int, Neuron] = {}
        for (_, subnet_netuid), neuron in self._neuron_cache.items():
            if subnet_netuid == subnet.netuid:
                uid_to_neuron[neuron.uid] = neuron

        collaterals_to_create = []
        for c in collaterals_data:
            source_uid = c.get("source_neuron_uid")
            target_uid = c.get("target_neuron_uid")

            source_neuron = uid_to_neuron.get(source_uid)
            target_neuron = uid_to_neuron.get(target_uid)

            if not source_neuron or not target_neuron:
                continue

            collaterals_to_create.append(
                Collateral(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    amount=_to_rao(c.get("amount", 0)),
                ),
            )

        if collaterals_to_create:
            Collateral.objects.bulk_create(
                collaterals_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(collaterals_to_create)

    def _sync_metagraph_dump(
        self,
        dump_data: dict[str, Any],
        block: Block,
        subnet: Subnet,
    ) -> MetagraphDump:
        """Sync a MetagraphDump record."""
        epoch_position_map = {"start": 0, "inside": 1, "end": 2}
        epoch_position = dump_data.get("epoch_position")
        if epoch_position and isinstance(epoch_position, str):
            epoch_position = epoch_position_map.get(epoch_position)

        # Use netuid from dump_data if available, otherwise use subnet.netuid
        netuid = dump_data.get("netuid") if dump_data.get("netuid") is not None else subnet.netuid

        dump, _ = MetagraphDump.objects.update_or_create(
            netuid=netuid,
            block=block,
            defaults={
                "epoch_position": epoch_position,
                "started_at": _parse_datetime(dump_data.get("started_at")),
                "finished_at": _parse_datetime(dump_data.get("finished_at")),
            },
        )
        return dump
