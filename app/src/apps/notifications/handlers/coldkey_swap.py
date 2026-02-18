from typing import Any, ClassVar

from apps.notifications.base import ExtrinsicNotification
from apps.notifications.channels import DiscordWebhookChannel
from apps.notifications.registry import register


@register
class ColdkeySwapNotification(ExtrinsicNotification):
    """Notification for coldkey swap events."""

    extrinsics: ClassVar[list[str]] = [
        "SubtensorModule:schedule_coldkey_swap",
        "SubtensorModule:swap_coldkey",
    ]
    channels: ClassVar = [DiscordWebhookChannel("DISCORD_COLDKEY_SWAP_WEBHOOK_URL")]

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
        call_args = extrinsic.get("call_args", [])

        params = []
        for arg in call_args:
            name = arg.get("name", "")
            if name == "netuid":
                continue
            params.append(f"**{name}**: `{self.format_value(arg.get('value'))}`")

        if params:
            return f"`{call_function}` — " + ", ".join(params)
        return f"`{call_function}`"
