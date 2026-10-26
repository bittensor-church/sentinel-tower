"""Record or revoke human-reviewed evidence for an exact historical gap."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.metagraph.models import Block, NeuronSnapshot, SnapshotGapAcknowledgement, Subnet
from apps.metagraph.utils import get_dumpable_blocks_in_range


class Command(BaseCommand):
    help = "Acknowledge one exact missing block for selected subnets; never repairs or fabricates data."

    def add_arguments(self, parser):
        parser.add_argument("--block", type=int, required=True)
        parser.add_argument("--netuids", type=int, nargs="+", required=True)
        parser.add_argument("--reason", choices=["upstream_unavailable", "retention"])
        parser.add_argument("--evidence", help="Archive checks or retained-source evidence reviewed by the operator")
        parser.add_argument("--revoke", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        block, netuids = options["block"], sorted(set(options["netuids"]))
        if block < 0 or set(Subnet.objects.filter(pk__in=netuids).values_list("pk", flat=True)) != set(netuids):
            raise CommandError("Use an existing subnet and a nonnegative block number.")
        if options["revoke"]:
            count = SnapshotGapAcknowledgement.objects.filter(
                netuid__in=netuids,
                block_number=block,
                revoked_at__isnull=True,
            ).update(revoked_at=timezone.now())
            self.stdout.write(f"Revoked {count} acknowledgements. Refresh snapshot health to publish the change.")
            return
        latest = (
            Block.objects.filter(timestamp__isnull=False).order_by("-number").values_list("number", flat=True).first()
        )
        if latest is None or block > latest:
            raise CommandError("Only historical gaps at or before the latest stored block may be acknowledged.")
        evidence = (options["evidence"] or "").strip()
        if options["reason"] not in ("upstream_unavailable", "retention") or not evidence:
            raise CommandError("Both --reason and nonempty --evidence are required; verify the cause first.")
        for netuid in netuids:
            if block not in get_dumpable_blocks_in_range(block, block, netuid):
                raise CommandError(f"Block {block} is not a scheduled snapshot for subnet {netuid}.")
            if NeuronSnapshot.objects.filter(neuron__subnet_id=netuid, block_id=block).exists():
                raise CommandError(f"Subnet {netuid} block {block} already has snapshots.")
            SnapshotGapAcknowledgement.objects.update_or_create(
                netuid=netuid,
                block_number=block,
                defaults={"reason": options["reason"], "evidence": evidence, "revoked_at": None},
            )
        self.stdout.write(
            f"Acknowledged block {block}, subnets {netuids}. Refresh snapshot health to publish the change."
        )
