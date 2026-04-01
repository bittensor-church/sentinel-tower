from django.core.management.base import BaseCommand

from apps.metagraph.services.coldkey_roles import resolve_coldkey_roles


class Command(BaseCommand):
    help = "Identify the roles of a Bittensor coldkey address (subnet owner, validator, miner)."

    def add_arguments(self, parser):
        parser.add_argument("address", type=str, help="SS58 coldkey address to look up")

    def handle(self, *args, **options):
        roles = resolve_coldkey_roles(options["address"])

        if roles.owned_subnets:
            self.stdout.write(f"Subnet Owner: {', '.join(str(n) for n in sorted(roles.owned_subnets))}")
        if roles.validator_subnets:
            self.stdout.write(f"Validator:    {', '.join(str(n) for n in sorted(roles.validator_subnets))}")
        if roles.miner_subnets:
            self.stdout.write(f"Miner:        {', '.join(str(n) for n in sorted(roles.miner_subnets))}")
        if not roles.all_netuids:
            self.stdout.write("No roles found for this address.")
