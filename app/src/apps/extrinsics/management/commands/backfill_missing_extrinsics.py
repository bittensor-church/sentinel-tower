from apps.extrinsics.models import Extrinsic

from django.core.management.base import BaseCommand
from apps.extrinsics.block_tasks import store_block_extrinsics
from apps.extrinsics.block_tasks import get_provider_for_block

class Command(BaseCommand):
    help = "Backfill missing extrinsics for recent blocks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--blocks",
            type=int,
            default=12000,
            help="Number of recent blocks to check for missing extrinsics (default: 12000)",
        )

    def handle(self, *args, **options):
        blocks: int = options["blocks"]

        max_block = Extrinsic.objects.order_by('-block_number').values_list('block_number', flat=True).first()

        if max_block is None:
            self.stdout.write("No extrinsics found in the database. Please run the initial backfill command first.")
            return

        existing = set(
            Extrinsic.objects.filter(block_number__gte=max_block - blocks)
            .values_list("block_number", flat=True)
            .distinct()
        )
        missing = sorted(set(range(max_block - blocks, max_block + 1)) - existing)
        self.stdout.write(f"Missing {len(missing)} blocks out of {blocks}. First 20: {missing[:20]}")

        with get_provider_for_block(missing[0], force_archive=True) as provider:
            for i, block_number in enumerate(missing):
                try:
                    result = store_block_extrinsics(block_number, provider)
                except Exception as e:
                    self.stdout.write(f"Error processing block {block_number}: {e}")
                    continue
                self.stdout.write(result or f"Block {block_number}: no extrinsics")
                self.stdout.write(f"{len(missing) - i - 1} blocks remaining...")
