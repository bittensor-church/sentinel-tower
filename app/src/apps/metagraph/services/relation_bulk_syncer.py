"""Bulk sync service for neuron-to-neuron relation records (weights, bonds, collaterals)."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.metagraph.models import Block, Bond, Collateral, Neuron, Subnet, Weight

if TYPE_CHECKING:
    from sentinel.v1.services.extractors.metagraph.dto import (
        Bond as BondDTO,
    )
    from sentinel.v1.services.extractors.metagraph.dto import (
        Collateral as CollateralDTO,
    )
    from sentinel.v1.services.extractors.metagraph.dto import (
        Weight as WeightDTO,
    )

# Conversion factor from TAO to rao (1 TAO = 10^9 rao)
TAO_TO_RAO = 10**9


def _to_rao(tao_value: float | str | Decimal | None) -> int:
    """Convert TAO value to rao (integer)."""
    if tao_value is None:
        return 0
    return int(Decimal(str(tao_value)) * TAO_TO_RAO)


class RelationBulkSyncer:
    """Bulk-creates Weight, Bond, and Collateral records from metagraph data.

    Takes a reference to the neuron cache from MetagraphSyncService to build
    UID-to-Neuron mappings without extra DB queries.
    """

    def __init__(self, neuron_cache: dict[tuple[int, int], Neuron]) -> None:
        self._neuron_cache = neuron_cache

    def _build_uid_to_neuron_map(self, subnet: Subnet) -> dict[int, Neuron]:
        """Build a UID-to-Neuron mapping for a subnet from the neuron cache."""
        uid_to_neuron: dict[int, Neuron] = {}
        for (_, subnet_netuid), neuron in self._neuron_cache.items():
            if subnet_netuid == subnet.netuid:
                uid_to_neuron[neuron.uid] = neuron
        return uid_to_neuron

    def sync_weights(
        self,
        weights: list[WeightDTO],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Weight records in bulk."""
        if not weights:
            return 0

        uid_to_neuron = self._build_uid_to_neuron_map(subnet)

        weights_to_create = []
        for w in weights:
            source_neuron = uid_to_neuron.get(w.source_neuron_uid)
            target_neuron = uid_to_neuron.get(w.target_neuron_uid)

            if not source_neuron or not target_neuron:
                continue

            weights_to_create.append(
                Weight(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    mech_id=w.mech_id,
                    weight=w.weight,
                ),
            )

        if weights_to_create:
            Weight.objects.bulk_create(
                weights_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(weights_to_create)

    def sync_bonds(
        self,
        bonds: list[BondDTO],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Bond records in bulk."""
        if not bonds:
            return 0

        uid_to_neuron = self._build_uid_to_neuron_map(subnet)

        bonds_to_create = []
        for b in bonds:
            source_neuron = uid_to_neuron.get(b.source_neuron_uid)
            target_neuron = uid_to_neuron.get(b.target_neuron_uid)

            if not source_neuron or not target_neuron:
                continue

            bonds_to_create.append(
                Bond(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    mech_id=b.mech_id,
                    bond=b.bond,
                ),
            )

        if bonds_to_create:
            Bond.objects.bulk_create(
                bonds_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(bonds_to_create)

    def sync_collaterals(
        self,
        collaterals: list[CollateralDTO],
        block: Block,
        subnet: Subnet,
    ) -> int:
        """Sync Collateral records in bulk."""
        if not collaterals:
            return 0

        uid_to_neuron = self._build_uid_to_neuron_map(subnet)

        collaterals_to_create = []
        for c in collaterals:
            source_neuron = uid_to_neuron.get(c.source_neuron_uid)
            target_neuron = uid_to_neuron.get(c.target_neuron_uid)

            if not source_neuron or not target_neuron:
                continue

            collaterals_to_create.append(
                Collateral(
                    source_neuron=source_neuron,
                    target_neuron=target_neuron,
                    block=block,
                    amount=_to_rao(c.amount),
                ),
            )

        if collaterals_to_create:
            Collateral.objects.bulk_create(
                collaterals_to_create,
                ignore_conflicts=True,
                batch_size=1000,
            )

        return len(collaterals_to_create)
