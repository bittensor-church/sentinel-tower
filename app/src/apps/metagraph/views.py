from django.conf import settings
from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Gauge, generate_latest

from apps.metagraph.models import Block, NeuronSnapshot, Subnet
from apps.metagraph.utils import get_dumpable_blocks_in_range

_WINDOWS = {
    "7d": 7 * 24 * 3600 // settings.BITTENSOR_SECONDS_PER_BLOCK,
    "12d": 12 * 24 * 3600 // settings.BITTENSOR_SECONDS_PER_BLOCK,
}


def snapshot_health_view(request) -> HttpResponse:
    """
    Determine for all subnets if and how many metagraph dumps have missing NeuronSnapshots.

    This view determines the blocks for which neuron snapshots are expected for each netuid using
    the logic defined in apps.metagraph.utils.get_dumpable_blocks_in_range and verifies that there
    is at least one neuron snapshot for each expected block/netuid pair.

    This endpoint is meant to be scraped by Prometheus.

    Returns:
        Prometheus-compatible metrics as an HttpResponse.
    """
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

        covered_by_netuid: dict[int, set[int]] = {}
        for block_id, subnet_id in (
            NeuronSnapshot.objects.filter(
                block_id__gte=start_block,
                block_id__lte=end_block,
                neuron__subnet_id__in=netuids,
            )
            .values_list("block_id", "neuron__subnet_id")
            .distinct()
        ):
            covered_by_netuid.setdefault(subnet_id, set()).add(block_id)

        for netuid in netuids:
            dumpable = set(get_dumpable_blocks_in_range(start_block, end_block, netuid))
            if not dumpable:
                continue
            missing_gauge.labels(netuid=str(netuid), window=window_name).set(
                len(dumpable - covered_by_netuid.get(netuid, set()))
            )

    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
