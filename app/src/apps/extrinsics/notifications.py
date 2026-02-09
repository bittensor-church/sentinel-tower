from typing import Any

import httpx
import structlog

from project.settings import DISCORD_ALERT_CONFIGS, AlertConfig

logger = structlog.get_logger()

# Constants for string truncation
MIN_LENGTH_FOR_TRUNCATION = 20
MAX_CALL_ARGS_LENGTH = 1000
MAX_LIST_ITEMS_DISPLAY = 3


def _format_call_args(call_args: list[dict[str, Any]] | None) -> str:
    """Format call arguments for display, truncating long values."""
    if not call_args:
        return "None"

    lines = []
    for arg in call_args:
        name = arg.get("name", "unknown")
        value = arg.get("value")

        # Format value based on type
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


def get_alert_config(call_module: str, call_function: str) -> AlertConfig | None:
    """Get the AlertConfig for the given call module/function."""
    for config in DISCORD_ALERT_CONFIGS:
        if config.matches(call_module, call_function):
            return config
    return None


def format_extrinsic_message(extrinsic: dict[str, Any]) -> dict[str, Any]:
    """Format extrinsic data for Discord embed."""
    call_module = extrinsic.get("call_module", "Unknown")
    call_function = extrinsic.get("call_function", "Unknown")
    block_number = extrinsic.get("block_number", "N/A")
    address = extrinsic.get("address", "N/A")
    extrinsic_hash = extrinsic.get("extrinsic_hash", "N/A")
    success = extrinsic.get("success", False)
    netuid = extrinsic.get("netuid")
    extrinsic_index = extrinsic.get("extrinsic_index", 0)
    extrinsic_index_formatted = f"{extrinsic_index:04d}" if isinstance(extrinsic_index, int) else "0000"
    tao_stats_link = f"https://taostats.io/extrinsic/{block_number}-{extrinsic_index_formatted}?network=finney"

    # Determine alert title
    module_titles = {
        "Sudo": "Sudo Extrinsic Detected",
        "AdminUtils": "AdminUtils Extrinsic Detected",
    }
    function_titles = {
        "register_network_with_identity": "Subnet Registration Detected",
        "schedule_coldkey_swap": "Coldkey Swap Detected",
        "swap_coldkey": "Coldkey Swap Detected",
    }

    title = module_titles.get(call_module) or function_titles.get(call_function, "Chain Event Detected")

    color = 0x00FF00 if success else 0xFF0000  # Green for success, red for failure

    fields = [
        {"name": "Module", "value": f"`{call_module}`", "inline": True},
        {"name": "Function", "value": f"`{call_function}`", "inline": True},
        {"name": "Block", "value": f"`{block_number}`", "inline": True},
        {"name": "Status", "value": "Success" if success else "Failed", "inline": True},
    ]

    if netuid is not None:
        fields.append({"name": "Netuid", "value": f"`{netuid}`", "inline": True})

    # Add call arguments if present
    call_args = extrinsic.get("call_args")
    if call_args:
        fields.append(
            {
                "name": "Parameters",
                "value": _format_call_args(call_args),
                "inline": False,
            }
        )

    fields.extend(
        [
            {"name": "Signer", "value": f"`{address or 'N/A'}`", "inline": False},
            {"name": "Hash", "value": f"`{extrinsic_hash}`", "inline": False},
            {"name": "TaoStats", "value": f"[View on TaoStats]({tao_stats_link})", "inline": False},
        ],
    )

    return {
        "embeds": [
            {
                "title": title,
                "url": tao_stats_link,
                "color": color,
                "fields": fields,
            },
        ],
    }


def send_discord_notification(extrinsic: dict[str, Any]) -> bool:
    """Send Discord notification for an extrinsic if it matches alert criteria."""
    call_module = extrinsic.get("call_module", "")
    call_function = extrinsic.get("call_function", "")

    if not (config := get_alert_config(call_module, call_function)):
        return False

    if not (webhook_url := config.get_webhook_url()):
        return False

    try:
        payload = format_extrinsic_message(extrinsic)

        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=payload)
            response.raise_for_status()

        logger.info(
            "Sent Discord notification",
            call_module=call_module,
            call_function=call_function,
            block_number=extrinsic.get("block_number"),
        )
    except httpx.HTTPStatusError as e:
        logger.warning(
            "Discord notification failed",
            status_code=e.response.status_code,
            call_module=call_module,
            call_function=call_function,
        )
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "Discord notification error",
            error=str(e),
            call_module=call_module,
            call_function=call_function,
        )
        return False
    else:
        return True


def notify_matching_extrinsics(extrinsics: list[dict[str, Any]]) -> int:
    """Send notifications for all extrinsics matching alert criteria."""
    notified = 0
    for extrinsic in extrinsics:
        if send_discord_notification(extrinsic):
            notified += 1
    return notified


def _format_extrinsic_line(extrinsic: dict[str, Any]) -> str:
    """Format a single extrinsic as a text line with old → new value format."""
    previous_values = extrinsic.get("previous_values", {})

    # Get the new value from call_args (skip netuid)
    call_args = extrinsic.get("call_args", [])
    new_value = None
    param_name = None
    for arg in call_args:
        name = arg.get("name", "")
        if name == "netuid":
            continue
        new_value = arg.get("value")
        param_name = name
        break

    # Format value for display
    def format_value(value: Any) -> str:
        if value is None:
            return "N/A"
        if isinstance(value, str) and len(value) > MIN_LENGTH_FOR_TRUNCATION:
            return f"{value[:8]}...{value[-6:]}"
        if isinstance(value, list) and len(value) > MAX_LIST_ITEMS_DISPLAY:
            return f"[{len(value)} items]"
        return str(value)

    # Get previous value from enriched data
    old_value = previous_values.get(param_name) if param_name and previous_values else None

    old_display = format_value(old_value)
    new_display = format_value(new_value)

    # Format: **hyperparam_name**: `prev_value` → `new_value`
    return f"**{param_name}**: `{old_display}` → `{new_display}`"


def _group_by_netuid(extrinsics: list[dict[str, Any]]) -> dict[int | None, list[dict[str, Any]]]:
    """Group extrinsics by netuid."""
    groups: dict[int | None, list[dict[str, Any]]] = {}
    for ext in extrinsics:
        netuid = ext.get("netuid")
        if netuid not in groups:
            groups[netuid] = []
        groups[netuid].append(ext)
    return groups


def format_block_notification(extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
    """Format multiple extrinsics from a block into a single Discord text message."""
    if not extrinsics:
        return {"content": "No extrinsics to report."}

    block_number = extrinsics[0].get("block_number", "N/A")
    extrinsic_index = extrinsics[0].get("extrinsic_index", 0)
    extrinsic_index_formatted = f"{extrinsic_index:04d}" if isinstance(extrinsic_index, int) else "0000"
    taostats_link = f"https://taostats.io/extrinsic/{block_number}-{extrinsic_index_formatted}?network=finney"

    lines = [f"**Block #{block_number}**", ""]

    # Group extrinsics by subnet
    netuid_groups = _group_by_netuid(extrinsics)
    for netuid in sorted(netuid_groups.keys(), key=lambda x: (x is None, x)):
        if netuid is None:
            lines.append("**Global**")
        else:
            lines.append(f"**Subnet {netuid}**")
        lines.extend(_format_extrinsic_line(ext) for ext in netuid_groups[netuid])
        lines.append("")

    lines.append(f"[View on TaoStats]({taostats_link})")

    return {
        "content": "\n".join(lines),
        "flags": 1 << 2,  # SUPPRESS_EMBEDS - disable link previews
    }


def _group_extrinsics_by_webhook(extrinsics: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group extrinsics by webhook URL, filtering to only successful extrinsics."""
    webhook_groups: dict[str, list[dict[str, Any]]] = {}

    for extrinsic in extrinsics:
        # Only show successful extrinsics
        if not extrinsic.get("success", False):
            continue

        call_module = extrinsic.get("call_module", "")
        call_function = extrinsic.get("call_function", "")

        if not (config := get_alert_config(call_module, call_function)):
            continue

        if not (webhook_url := config.get_webhook_url()):
            continue

        if webhook_url not in webhook_groups:
            webhook_groups[webhook_url] = []
        webhook_groups[webhook_url].append(extrinsic)

    return webhook_groups


def send_block_notifications(block_number: int, extrinsics: list[dict[str, Any]]) -> int:
    """
    Send aggregated Discord notifications for all matching extrinsics in a block.

    Groups extrinsics by webhook URL and sends a single message per webhook.
    Returns the number of extrinsics that were notified.
    """
    if not extrinsics:
        return 0

    if not (webhook_groups := _group_extrinsics_by_webhook(extrinsics)):
        return 0

    notified_count = 0

    for webhook_url, grouped_extrinsics in webhook_groups.items():
        try:
            payload = format_block_notification(grouped_extrinsics)

            with httpx.Client(timeout=10.0) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()

            notified_count += len(grouped_extrinsics)
            logger.info(
                "Sent aggregated Discord notification",
                block_number=block_number,
                extrinsic_count=len(grouped_extrinsics),
            )
        except httpx.HTTPStatusError as e:
            logger.warning(
                "Discord block notification failed",
                status_code=e.response.status_code,
                block_number=block_number,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Discord block notification error",
                error=str(e),
                block_number=block_number,
            )

    return notified_count
