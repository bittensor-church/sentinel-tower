from dataclasses import dataclass, field


@dataclass
class ColdkeyRoles:
    """Roles associated with a coldkey address."""

    owned_subnets: list[int] = field(default_factory=list)
    validator_subnets: list[int] = field(default_factory=list)
    miner_subnets: list[int] = field(default_factory=list)

    @property
    def all_netuids(self) -> set[int]:
        return {*self.owned_subnets, *self.validator_subnets, *self.miner_subnets}

    def format_lines(self) -> list[str]:
        lines: list[str] = []
        if self.owned_subnets:
            netuids = ", ".join(str(n) for n in sorted(self.owned_subnets))
            lines.append(f"**role**: Subnet Owner (SN {netuids})")
        if self.validator_subnets:
            netuids = ", ".join(str(n) for n in sorted(self.validator_subnets))
            lines.append(f"**role**: Validator (SN {netuids})")
        if self.miner_subnets:
            netuids = ", ".join(str(n) for n in sorted(self.miner_subnets))
            lines.append(f"**role**: Miner (SN {netuids})")
        if not lines:
            lines.append("**role**: Unknown")
        return lines


def resolve_coldkey_roles(address: str) -> ColdkeyRoles:
    """Look up the roles of a coldkey address in the database."""
    from apps.metagraph.models import NeuronSnapshot, Subnet

    roles = ColdkeyRoles()

    # Subnet ownership: Subnet -> owner_hotkey -> coldkey
    owned = Subnet.objects.filter(
        owner_hotkey__coldkey__coldkey=address,
    ).values_list("netuid", flat=True)
    roles.owned_subnets = list(owned)

    # Validator / miner: latest snapshot per neuron for this coldkey
    latest_snapshots = (
        NeuronSnapshot.objects.filter(
            neuron__hotkey__coldkey__coldkey=address,
        )
        .order_by("neuron", "-block__number")
        .distinct("neuron")
        .select_related("neuron__subnet")
    )
    for snap in latest_snapshots:
        netuid = snap.neuron.subnet_id
        if snap.is_validator:
            roles.validator_subnets.append(netuid)
        else:
            roles.miner_subnets.append(netuid)

    return roles
