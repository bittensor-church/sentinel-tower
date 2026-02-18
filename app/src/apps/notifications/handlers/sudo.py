from typing import Any, ClassVar

from apps.notifications.base import ExtrinsicNotification
from apps.notifications.channels import DiscordWebhookChannel
from apps.notifications.registry import register


@register
class SudoNotification(ExtrinsicNotification):
    """Catch-all notification for Sudo extrinsics not matched by specific handlers."""

    extrinsics: ClassVar[list[str]] = ["Sudo"]
    channels: ClassVar = [DiscordWebhookChannel("DISCORD_SUDO_ALERTS_WEBHOOK_URL")]

    def format_message(self, block_number: int, extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
        first = extrinsics[0]
        link = self.taostats_link(block_number, first.get("extrinsic_index", 0))
        unwrapped = [self.unwrap_sudo_call(e) for e in extrinsics]

        lines = [f"**Block #{block_number}**", ""]

        for netuid, group in sorted(
            self.group_by_netuid(unwrapped).items(),
            key=lambda x: (x[0] is None, x[0]),
        ):
            lines.append(f"**Subnet {netuid}**" if netuid is not None else "**Global**")
            for ext in group:
                lines.append(self._format_generic(ext))
            lines.append("")

        lines.append(f"[View on TaoStats]({link})")
        return {"content": "\n".join(lines), "flags": 1 << 2}

    def _format_generic(self, extrinsic: dict[str, Any]) -> str:
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
