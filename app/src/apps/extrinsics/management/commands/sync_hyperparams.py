"""Sync subnet hyperparameters from the blockchain."""

from django.core.management.base import BaseCommand
from sentinel.v1.services.sentinel import sentinel_service

from apps.extrinsics.models import SubnetHyperparam
from project.core.utils import get_provider_for_block

# Mapping of HyperparametersDTO field names to our storage keys
HYPERPARAM_FIELD_MAP = {
    "tempo": "tempo",
    "weights_rate_limit": "weights_rate_limit",
    "adjustment_interval": "adjustment_interval",
    "target_regs_per_interval": "target_registrations_per_interval",
    "activity_cutoff": "activity_cutoff",
    "max_validators": "max_allowed_validators",
    "min_allowed_weights": "min_allowed_weights",
    "max_weight_limit": "max_weight_limit",
    "immunity_period": "immunity_period",
    "min_difficulty": "min_difficulty",
    "max_difficulty": "max_difficulty",
    "weights_version": "weights_version_key",
    "bonds_moving_avg": "bonds_moving_average",
    "commit_reveal_weights_interval": "commit_reveal_weights_interval",
    "commit_reveal_weights_enabled": "commit_reveal_weights_enabled",
    "alpha_high": "alpha_high",
    "alpha_low": "alpha_low",
    "registration_allowed": "registration_allowed",
    "adjustment_alpha": "adjustment_alpha",
    "min_burn": "min_burn",
    "max_burn": "max_burn",
    "serving_rate_limit": "serving_rate_limit",
    "kappa": "kappa",
    "rho": "rho",
    "liquid_alpha_enabled": "liquid_alpha_enabled",
}


class Command(BaseCommand):
    help = "Sync subnet hyperparameters from the blockchain to the database."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "netuids",
            nargs="*",
            type=int,
            help="List of subnet IDs to sync (default: all registered subnets)",
        )
        parser.add_argument(
            "--block",
            type=int,
            default=None,
            help="Block number to fetch hyperparams from (default: latest)",
        )

    def handle(self, *args, **kwargs):
        netuids = kwargs["netuids"]
        block_number = kwargs["block"]

        with get_provider_for_block(block_number or 0, force_archive=bool(block_number)) as provider:
            service = sentinel_service(provider)

            # Get current block if not specified
            if not block_number:
                block_number = provider.get_current_block()
                self.stdout.write(f"Using current block: {block_number}")

            # If no netuids specified, get all registered subnets
            if not netuids:
                self.stdout.write("Fetching list of registered subnets...")
                try:
                    netuids = provider.get_all_subnets_netuids()
                    self.stdout.write(f"Found {len(netuids)} subnets: {netuids}")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Error getting subnet list: {e}"))
                    return

            synced_count = 0
            error_count = 0

            for netuid in netuids:
                try:
                    self.stdout.write(f"Syncing subnet {netuid}...")
                    subnet = service.ingest_subnet(netuid, block_number)

                    if not subnet:
                        self.stdout.write(self.style.WARNING(f"  Subnet {netuid} not found"))
                        continue

                    hyperparams = subnet.hyperparameters
                    if not hyperparams:
                        self.stdout.write(self.style.WARNING(f"  No hyperparams for subnet {netuid}"))
                        continue

                    # Get all hyperparams as a dict from the Pydantic model
                    hyperparams_dict = hyperparams.model_dump()

                    # Sync each hyperparam
                    params_synced = 0
                    for field_name, storage_key in HYPERPARAM_FIELD_MAP.items():
                        if field_name in hyperparams_dict:
                            value = hyperparams_dict[field_name]
                            SubnetHyperparam.objects.update_or_create(
                                netuid=netuid,
                                param_name=storage_key,
                                defaults={
                                    "value": value,
                                    "last_block_number": block_number,
                                },
                            )
                            params_synced += 1

                    self.stdout.write(
                        self.style.SUCCESS(f"  Synced {params_synced} params for subnet {netuid}")
                    )
                    synced_count += 1

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  Error syncing subnet {netuid}: {e}"))
                    error_count += 1

            self.stdout.write("")
            self.stdout.write(
                self.style.SUCCESS(f"Sync complete: {synced_count} subnets synced, {error_count} errors")
            )
