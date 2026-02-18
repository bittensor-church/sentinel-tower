import abc
from typing import Any, ClassVar

import structlog

from apps.notifications.channels import NotificationChannel

logger = structlog.get_logger()

# Constants for string truncation
MIN_LENGTH_FOR_TRUNCATION = 20
MAX_CALL_ARGS_LENGTH = 1000
MAX_LIST_ITEMS_DISPLAY = 3


class ExtrinsicNotification(abc.ABC):
    """Base class for extrinsic-based notifications.

    Subclasses declare which extrinsic patterns they handle, which channels
    to deliver to, and how to format the message.

    Attributes:
        extrinsics: Patterns to match, e.g. ["AdminUtils"] (whole module)
                    or ["SubtensorModule:register_network"] (specific function).
        channels: Notification channels to deliver to.
        success_only: If True, only successful extrinsics are notified.
    """

    extrinsics: ClassVar[list[str]]
    channels: ClassVar[list[NotificationChannel]]
    success_only: ClassVar[bool] = True

    def matches(self, call_module: str, call_function: str) -> bool:
        """Check if this notification handles the given module/function."""
        for pattern in self.extrinsics:
            if ":" in pattern:
                p_module, p_function = pattern.split(":", 1)
                if call_module == p_module and call_function == p_function:
                    return True
            elif call_module == pattern:
                return True
        return False

    @abc.abstractmethod
    def format_message(self, block_number: int, extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the notification payload for a group of matched extrinsics."""
        ...

    def notify(self, block_number: int, extrinsics: list[dict[str, Any]]) -> int:
        """Filter extrinsics, format, and send to all channels. Returns count notified."""
        if self.success_only:
            extrinsics = [e for e in extrinsics if e.get("success", False)]

        if not extrinsics:
            return 0

        payload = self.format_message(block_number, extrinsics)
        sent = False
        for channel in self.channels:
            if channel.send(payload):
                sent = True

        if sent:
            logger.info(
                "Notification sent",
                notification=self.__class__.__name__,
                block_number=block_number,
                extrinsic_count=len(extrinsics),
            )
            return len(extrinsics)
        return 0

    # ── Shared formatting utilities ──────────────────────────────────────

    @staticmethod
    def unwrap_sudo_call(extrinsic: dict[str, Any]) -> dict[str, Any]:
        """Unwrap a Sudo extrinsic to extract the inner call details."""
        call_module = extrinsic.get("call_module", "")
        call_function = extrinsic.get("call_function", "")

        if call_module != "Sudo" or call_function != "sudo":
            return extrinsic

        call_args = extrinsic.get("call_args", [])
        for arg in call_args:
            if arg.get("name") == "call" and isinstance(arg.get("value"), dict):
                inner = arg["value"]
                inner_args = inner.get("call_args", [])
                netuid = extrinsic.get("netuid")
                if netuid is None:
                    for inner_arg in inner_args:
                        if inner_arg.get("name") == "netuid":
                            netuid = inner_arg.get("value")
                            break
                return {
                    **extrinsic,
                    "call_module": inner.get("call_module", call_module),
                    "call_function": inner.get("call_function", call_function),
                    "call_args": inner_args,
                    "netuid": netuid,
                    "_is_sudo": True,
                }

        return extrinsic

    @staticmethod
    def format_value(value: Any) -> str:
        """Format a value for display, truncating long lists."""
        if value is None:
            return "N/A"
        if isinstance(value, list) and len(value) > MAX_LIST_ITEMS_DISPLAY:
            return f"[{len(value)} items]"
        return str(value)

    @staticmethod
    def format_call_args(call_args: list[dict[str, Any]] | None) -> str:
        """Format call arguments for display, truncating long values."""
        if not call_args:
            return "None"

        lines = []
        for arg in call_args:
            name = arg.get("name", "unknown")
            value = arg.get("value")

            if isinstance(value, str) and len(value) > MIN_LENGTH_FOR_TRUNCATION:
                value_display = f"{value[:10]}...{value[-8:]}"
            elif isinstance(value, dict):
                value_display = "{...}"
            elif isinstance(value, list) and len(value) > MAX_LIST_ITEMS_DISPLAY:
                value_display = f"[{len(value)} items]"
            else:
                value_display = str(value)

            lines.append(f"**{name}**: `{value_display}`")

        result = "\n".join(lines)
        if len(result) > MAX_CALL_ARGS_LENGTH:
            result = result[:MAX_CALL_ARGS_LENGTH] + "..."
        return result

    @staticmethod
    def decode_hex_field(value: Any) -> str:
        """Decode a hex-encoded bytes field (e.g. SubnetIdentityV3 Vec<u8> fields)."""
        if not isinstance(value, str):
            return str(value) if value else ""
        try:
            text = value.removeprefix("0x")
            return bytes.fromhex(text).decode("utf-8", errors="replace").strip("\x00")
        except (ValueError, UnicodeDecodeError):
            return value

    @staticmethod
    def taostats_link(block_number: int | str, extrinsic_index: int = 0) -> str:
        """Build a TaoStats extrinsic URL."""
        idx = f"{extrinsic_index:04d}" if isinstance(extrinsic_index, int) else "0000"
        return f"https://taostats.io/extrinsic/{block_number}-{idx}?network=finney"

    @staticmethod
    def group_by_netuid(extrinsics: list[dict[str, Any]]) -> dict[int | None, list[dict[str, Any]]]:
        """Group extrinsics by netuid."""
        groups: dict[int | None, list[dict[str, Any]]] = {}
        for ext in extrinsics:
            netuid = ext.get("netuid")
            groups.setdefault(netuid, []).append(ext)
        return groups
