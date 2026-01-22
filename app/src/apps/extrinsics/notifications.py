import os
from typing import Any

import httpx
import structlog

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

# Alert configurations: (call_module, call_function or None for all) -> env var name
ALERT_CONFIGS = {
    ("Sudo", None): "DISCORD_SUDO_ALERTS_WEBHOOK_URL",
    ("AdminUtils", None): "DISCORD_ADMIN_UTILS_ALERTS_WEBHOOK_URL",
    ("SubtensorModule", "register_network"): "DISCORD_SUBNET_REGISTRATION_WEBHOOK_URL",
    ("SubtensorModule", "schedule_coldkey_swap"): "DISCORD_COLDKEY_SWAP_WEBHOOK_URL",
    ("SubtensorModule", "swap_coldkey"): "DISCORD_COLDKEY_SWAP_WEBHOOK_URL",
}

def is_disabled_url(url: str) -> bool:
    """Check if a webhook URL is disabled or a placeholder."""
    return not url or "disabled" in url or url == "https://discord.com/api/webhooks/0/disabled"


def get_webhook_url(call_module: str, call_function: str) -> str | None:
    """Get Discord webhook URL for the given call module/function."""
    # Check specific module+function first
    env_var = ALERT_CONFIGS.get((call_module, call_function))
    if not env_var:
        # Check module-only match (for Sudo)
        env_var = ALERT_CONFIGS.get((call_module, None))

    if not env_var:
        return None

    url = os.environ.get(env_var, "")

    # Skip disabled/placeholder URLs
    if is_disabled_url(url):
        return None

    return url


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

    # Determine alert type and color
    if call_module == "Sudo":
        title = "Sudo Extrinsic Detected"
        color = 0xFF0000  # Red
    elif call_module == "AdminUtils":
        title = "AdminUtils Extrinsic Detected"
        color = 0xFF4500  # Orange Red
    elif call_function == "register_network":
        title = "Subnet Registration Detected"
        color = 0x0099FF  # Blue
    elif call_function in ("schedule_coldkey_swap", "swap_coldkey"):
        title = "Coldkey Swap Detected"
        color = 0xFFA500  # Orange
    else:
        title = "Chain Event Detected"
        color = 0x808080  # Gray

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
    import pdb; pdb.set_trace()
    if call_args:
        fields.append({
            "name": "Parameters",
            "value": _format_call_args(call_args),
            "inline": False,
        })

    # Truncate address and hash for display
    address_display = (
        f"{address[:10]}...{address[-8:]}"
        if address and len(address) > MIN_LENGTH_FOR_TRUNCATION
        else address or "N/A"
    )

    if extrinsic_hash and len(extrinsic_hash) > MIN_LENGTH_FOR_TRUNCATION:
        hash_display = f"{extrinsic_hash[:10]}...{extrinsic_hash[-8:]}"
    else:
        hash_display = extrinsic_hash or "N/A"

    fields.extend(
        [
            {"name": "Signer", "value": f"`{address_display}`", "inline": False},
            {"name": "Hash", "value": f"`{hash_display}`", "inline": False},
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

    webhook_url = get_webhook_url(call_module, call_function)
    if not webhook_url:
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
