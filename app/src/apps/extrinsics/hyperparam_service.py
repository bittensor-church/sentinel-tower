"""Service for tracking subnet hyperparameter changes."""

from typing import Any

import structlog

from apps.extrinsics.models import SubnetHyperparam, SubnetHyperparamHistory

logger = structlog.get_logger()

# Mapping from AdminUtils function names to the hyperparam they set
# Format: function_name -> (param_name_in_call_args, storage_key)
HYPERPARAM_FUNCTION_MAP: dict[str, str] = {
    "sudo_set_tempo": "tempo",
    "sudo_set_weights_set_rate_limit": "weights_rate_limit",
    "sudo_set_adjustment_interval": "adjustment_interval",
    "sudo_set_target_registrations_per_interval": "target_registrations_per_interval",
    "sudo_set_activity_cutoff": "activity_cutoff",
    "sudo_set_max_allowed_validators": "max_allowed_validators",
    "sudo_set_min_allowed_weights": "min_allowed_weights",
    "sudo_set_max_weight_limit": "max_weight_limit",
    "sudo_set_immunity_period": "immunity_period",
    "sudo_set_min_difficulty": "min_difficulty",
    "sudo_set_max_difficulty": "max_difficulty",
    "sudo_set_weights_version_key": "weights_version_key",
    "sudo_set_bonds_moving_average": "bonds_moving_average",
    "sudo_set_commit_reveal_weights_interval": "commit_reveal_weights_interval",
    "sudo_set_commit_reveal_weights_enabled": "commit_reveal_weights_enabled",
    "sudo_set_alpha_values": "alpha_values",
    "sudo_set_network_pow_registration_allowed": "pow_registration_allowed",
    "sudo_set_network_registration_allowed": "registration_allowed",
    "sudo_set_adjustment_alpha": "adjustment_alpha",
    "sudo_set_min_burn": "min_burn",
    "sudo_set_max_burn": "max_burn",
    "sudo_set_serving_rate_limit": "serving_rate_limit",
    "sudo_set_kappa": "kappa",
    "sudo_set_rho": "rho",
    "sudo_set_liquid_alpha_enabled": "liquid_alpha_enabled",
}


def get_hyperparam_name(call_function: str) -> str | None:
    """Get the hyperparam name for a given AdminUtils function."""
    return HYPERPARAM_FUNCTION_MAP.get(call_function)


def get_previous_value(netuid: int, param_name: str) -> Any | None:
    """
    Get the previous value of a hyperparam for a subnet.

    Returns None if no previous value is stored.
    """
    try:
        record = SubnetHyperparam.objects.get(netuid=netuid, param_name=param_name)
        return record.value
    except SubnetHyperparam.DoesNotExist:
        return None


def update_hyperparam(
    netuid: int,
    param_name: str,
    value: Any,
    block_number: int,
    *,
    extrinsic_hash: str = "",
    address: str = "",
    success: bool = True,
) -> Any | None:
    """
    Update the stored hyperparam value and return the previous value.

    Also records the change in history for Grafana dashboards.
    Returns the previous value (or None if this is the first time tracking).
    """
    previous_value = None

    record, created = SubnetHyperparam.objects.get_or_create(
        netuid=netuid,
        param_name=param_name,
        defaults={"value": value, "last_block_number": block_number},
    )

    if not created:
        previous_value = record.value
        record.value = value
        record.last_block_number = block_number
        record.save()

    # Record history for Grafana time-series visualization
    SubnetHyperparamHistory.objects.create(
        netuid=netuid,
        param_name=param_name,
        old_value=previous_value,
        new_value=value,
        block_number=block_number,
        extrinsic_hash=extrinsic_hash,
        address=address,
        success=success,
    )

    logger.debug(
        "Updated hyperparam",
        netuid=netuid,
        param_name=param_name,
        previous_value=previous_value,
        new_value=value,
        block_number=block_number,
    )

    return previous_value


def enrich_extrinsic_with_previous_values(extrinsic: dict[str, Any]) -> dict[str, Any]:
    """
    Enrich an extrinsic with previous hyperparam values.

    For AdminUtils extrinsics that change hyperparams, adds a 'previous_values'
    dict mapping param names to their previous values.

    Also updates the stored hyperparam values.
    """
    call_module = extrinsic.get("call_module", "")
    call_function = extrinsic.get("call_function", "")
    netuid = extrinsic.get("netuid")
    block_number = extrinsic.get("block_number", 0)
    success = extrinsic.get("success", False)

    # Only process AdminUtils extrinsics with a netuid
    if call_module != "AdminUtils" or netuid is None:
        return extrinsic

    param_name = get_hyperparam_name(call_function)
    if not param_name:
        return extrinsic

    # Get the new value from call_args
    call_args = extrinsic.get("call_args", [])
    new_value = None
    for arg in call_args:
        # Skip netuid arg
        if arg.get("name") == "netuid":
            continue
        # Take the first non-netuid arg as the value
        new_value = arg.get("value")
        break

    if new_value is None:
        return extrinsic

    extrinsic_hash = extrinsic.get("extrinsic_hash", "")
    address = extrinsic.get("address", "")

    # Get and update the previous value (only update if extrinsic succeeded)
    if success:
        previous_value = update_hyperparam(
            netuid,
            param_name,
            new_value,
            block_number,
            extrinsic_hash=extrinsic_hash,
            address=address,
            success=True,
        )
    else:
        # For failed extrinsics, just get the current value without updating
        previous_value = get_previous_value(netuid, param_name)

    # Add previous value to extrinsic
    extrinsic = extrinsic.copy()
    extrinsic["previous_values"] = {param_name: previous_value}

    return extrinsic


def enrich_extrinsics_with_previous_values(
    extrinsics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Enrich a list of extrinsics with previous hyperparam values."""
    return [enrich_extrinsic_with_previous_values(ext) for ext in extrinsics]
