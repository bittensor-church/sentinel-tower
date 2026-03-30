from typing import Any, ClassVar

from apps.notifications.base import ExtrinsicNotification
from apps.notifications.channels import DiscordWebhookChannel
from apps.notifications.registry import register

_ACTION_LABELS: dict[str, str] = {
    "announce_coldkey_swap": "Coldkey Swap Announced",
    "swap_coldkey_announced": "Coldkey Swap Executed",
    "dispute_coldkey_swap": "Coldkey Swap Disputed",
    "reset_coldkey_swap": "Coldkey Swap Reset",
    "clear_coldkey_swap_announcement": "Coldkey Swap Cleared",
}


@register
class ColdkeySwapNotification(ExtrinsicNotification):
    """Notification for coldkey swap events.

    Covers the full announce -> wait -> execute lifecycle plus
    dispute, reset, and clear actions.
    """

    extrinsics: ClassVar[list[str]] = [
        "SubtensorModule:announce_coldkey_swap",
        "SubtensorModule:swap_coldkey_announced",
        "SubtensorModule:dispute_coldkey_swap",
        "SubtensorModule:reset_coldkey_swap",
        "SubtensorModule:clear_coldkey_swap_announcement",
    ]
    channel: ClassVar = DiscordWebhookChannel("DISCORD_COLDKEY_SWAP_WEBHOOK_URL")

    def format_message(self, block_number: int, extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
        first = extrinsics[0]
        link = self.taostats_link(block_number, first.get("extrinsic_index", 0))
        unwrapped = [self.unwrap_sudo_call(e) for e in extrinsics]

        lines = [f"**Block #{block_number}**", ""]

        for ext in unwrapped:
            lines.append(self._format_swap(ext))
            lines.append("")

        lines.append(f"[View on TaoStats]({link})")
        return {"content": "\n".join(lines), "flags": 1 << 2}

    def _format_swap(self, extrinsic: dict[str, Any]) -> str:
        call_function = extrinsic.get("call_function", "unknown")
        label = _ACTION_LABELS.get(call_function, call_function)
        address = extrinsic.get("address", "")
        call_args = extrinsic.get("call_args", [])

        parts = [f"**{label}**"]
        if address:
            parts.append(f"**signer**: `{address}`")

        for arg in call_args:
            name = arg.get("name", "")
            parts.append(f"**{name}**: `{self.format_value(arg.get('value'))}`")

        return "\n".join(parts)
