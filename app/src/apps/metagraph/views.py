from django.conf import settings
from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from apps.metagraph.models import Block, NeuronSnapshot, Subnet
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

_BLOCK_SECONDS = 12
_WINDOWS = {
    "7d": 7 * 24 * 3600 // _BLOCK_SECONDS,
    "12d": 12 * 24 * 3600 // _BLOCK_SECONDS,
}


def _dumpable_blocks_in_range(start: int, end: int, netuid: int) -> list[int]:
    result: set[int] = set()
    block = start
    while block <= end:
        epoch = get_epoch_containing_block(block, netuid)
        for b in get_dumpable_blocks(epoch):
            if start <= b <= end:
                result.add(b)
        block = epoch.stop
    return sorted(result)


def snapshot_health_view(request):
    latest_block = Block.objects.filter(timestamp__isnull=False).order_by("-number").first()
    if not latest_block:
        return HttpResponse(b"", content_type=CONTENT_TYPE_LATEST)

    netuids: list[int] = settings.METAGRAPH_NETUIDS or list(Subnet.objects.values_list("netuid", flat=True))

    registry = CollectorRegistry()
    missing_gauge = Gauge(
        "metagraph_missing_snapshot_blocks",
        "Dumpable blocks with no NeuronSnapshot entries for this netuid in the look-back window",
        ["netuid", "window"],
        registry=registry,
    )

    for window_name, block_delta in _WINDOWS.items():
        start_block = latest_block.number - block_delta
        end_block = latest_block.number

        for netuid in netuids:
            dumpable = _dumpable_blocks_in_range(start_block, end_block, netuid)
            if not dumpable:
                continue

            covered = set(
                NeuronSnapshot.objects.filter(
                    block_id__in=dumpable,
                    neuron__subnet_id=netuid,
                )
                .values_list("block_id", flat=True)
                .distinct()
            )

            missing_gauge.labels(netuid=str(netuid), window=window_name).set(len(set(dumpable) - covered))

    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
