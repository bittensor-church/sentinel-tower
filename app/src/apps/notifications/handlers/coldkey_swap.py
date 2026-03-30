from dataclasses import dataclass, field
from typing import Any, ClassVar

import structlog

from apps.notifications.base import SubnetRoutedNotification
from apps.notifications.channels import DiscordWebhookChannel
from apps.notifications.registry import register

logger = structlog.get_logger()

_ACTION_LABELS: dict[str, str] = {
    "announce_coldkey_swap": "Coldkey Swap Announced",
    "swap_coldkey_announced": "Coldkey Swap Executed",
    "dispute_coldkey_swap": "Coldkey Swap Disputed",
    "reset_coldkey_swap": "Coldkey Swap Reset",
    "clear_coldkey_swap_announcement": "Coldkey Swap Cleared",
}


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


def _resolve_coldkey_roles(address: str) -> ColdkeyRoles:
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


@register
class ColdkeySwapNotification(SubnetRoutedNotification):
    """Notification for coldkey swap events.

    Covers the full announce -> wait -> execute lifecycle plus
    dispute, reset, and clear actions.

    Since coldkey swap extrinsics carry no netuid, the handler looks up
    the signer's roles (subnet owner / validator / miner) and routes
    notifications to all associated subnets.
    """

    extrinsics: ClassVar[list[str]] = [
        "SubtensorModule:announce_coldkey_swap",
        "SubtensorModule:swap_coldkey_announced",
        "SubtensorModule:dispute_coldkey_swap",
        "SubtensorModule:reset_coldkey_swap",
        "SubtensorModule:clear_coldkey_swap_announcement",
    ]
    fallback_channel: ClassVar = DiscordWebhookChannel("DISCORD_COLDKEY_SWAP_WEBHOOK_URL")

    def notify(self, block_number: int, extrinsics: list[dict[str, Any]]) -> int:
        """Enrich extrinsics with coldkey roles and discovered netuids, then route."""
        if self.success_only:
            extrinsics = [e for e in extrinsics if e.get("success", False)]

        if not extrinsics:
            return 0

        # Resolve roles for each unique signer and attach to extrinsics
        roles_cache: dict[str, ColdkeyRoles] = {}
        enriched: list[dict[str, Any]] = []
        for ext in extrinsics:
            address = ext.get("address", "")
            if address and address not in roles_cache:
                try:
                    roles_cache[address] = _resolve_coldkey_roles(address)
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to resolve coldkey roles", address=address)
                    roles_cache[address] = ColdkeyRoles()

            roles = roles_cache.get(address, ColdkeyRoles())
            netuids = roles.all_netuids

            if netuids:
                # Fan out to each associated subnet for routing
                for netuid in netuids:
                    enriched.append({**ext, "netuid": netuid, "_coldkey_roles": roles})
            else:
                enriched.append({**ext, "_coldkey_roles": roles})

        return super().notify(block_number, enriched)

    def format_message(self, block_number: int, extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
        first = extrinsics[0]
        link = self.taostats_link(block_number, first.get("extrinsic_index", 0))
        unwrapped = [self.unwrap_sudo_call(e) for e in extrinsics]

        # Deduplicate: when fanned out, the same extrinsic appears per-netuid
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for ext in unwrapped:
            key = (ext.get("extrinsic_hash", ""), ext.get("call_function", ""))
            if key not in seen:
                seen.add(key)
                unique.append(ext)

        lines = [f"**Block #{block_number}**", ""]

        for ext in unique:
            lines.append(self._format_swap(ext))
            lines.append("")

        lines.append(f"[View on TaoStats]({link})")
        return {"content": "\n".join(lines), "flags": 1 << 2}

    def _format_swap(self, extrinsic: dict[str, Any]) -> str:
        call_function = extrinsic.get("call_function", "unknown")
        label = _ACTION_LABELS.get(call_function, call_function)
        address = extrinsic.get("address", "")
        call_args = extrinsic.get("call_args", [])
        roles: ColdkeyRoles = extrinsic.get("_coldkey_roles", ColdkeyRoles())

        parts = [f"**{label}**"]
        if address:
            parts.append(f"**signer**: `{address}`")

        parts.extend(roles.format_lines())

        for arg in call_args:
            name = arg.get("name", "")
            parts.append(f"**{name}**: `{self.format_value(arg.get('value'))}`")

        return "\n".join(parts)
