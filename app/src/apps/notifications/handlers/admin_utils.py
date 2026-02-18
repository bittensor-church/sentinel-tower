from typing import Any, ClassVar

from apps.notifications.base import ExtrinsicNotification
from apps.notifications.channels import DiscordWebhookChannel
from apps.notifications.registry import register


@register
class AdminUtilsNotification(ExtrinsicNotification):
    """Notification for AdminUtils hyperparam changes.

    Displays parameter changes in ``old → new`` format, grouped by subnet.
    """

    extrinsics: ClassVar[list[str]] = ["AdminUtils"]
    channels: ClassVar = [DiscordWebhookChannel("DISCORD_ADMIN_UTILS_ALERTS_WEBHOOK_URL")]

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
                lines.append(self._format_param_change(ext))
            lines.append("")

        lines.append(f"[View on TaoStats]({link})")
        return {"content": "\n".join(lines), "flags": 1 << 2}

    @staticmethod
    def _format_param_change(extrinsic: dict[str, Any]) -> str:
        call_args = extrinsic.get("call_args", [])
        previous_values = extrinsic.get("previous_values", {})

        new_value = None
        param_name = None
        for arg in call_args:
            name = arg.get("name", "")
            if name == "netuid":
                continue
            new_value = arg.get("value")
            param_name = name
            break

        old_value = previous_values.get(param_name) if param_name and previous_values else None
        old_display = ExtrinsicNotification.format_value(old_value)
        new_display = ExtrinsicNotification.format_value(new_value)
        return f"**{param_name}**: `{old_display}` → `{new_display}`"
