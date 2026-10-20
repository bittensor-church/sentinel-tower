from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.test import override_settings
from prometheus_client.parser import text_string_to_metric_families

from apps.metagraph.models import SnapshotHealthMetric
from apps.metagraph.tasks import (
    update_snapshot_health_metrics,
)
from apps.metagraph.utils import get_dumpable_blocks_in_range
from tests.factories.metagraph import BlockFactory, NeuronFactory, NeuronSnapshotFactory, SubnetFactory


def _gauge_value(content: str, netuid: int, window: str) -> float:
    """Return the metagraph_missing_snapshot_blocks value for the netuid/window pair."""
    for family in text_string_to_metric_families(content):
        if family.name != "metagraph_missing_snapshot_blocks":
            continue
        for sample in family.samples:
            if sample.labels.get("netuid") == str(netuid) and sample.labels.get("window") == window:
                return sample.value
    raise KeyError(f"metric not found: netuid={netuid} window={window}")


@pytest.fixture()
def latest_block():
    return BlockFactory(number=1000, timestamp=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture()
def neuron():
    subnet = SubnetFactory(netuid=1)
    return NeuronFactory(subnet=subnet)


@pytest.fixture()
def other_neuron():
    subnet = SubnetFactory(netuid=1)
    return NeuronFactory(subnet=subnet)


@pytest.mark.django_db
def test_no_latest_block_persists_nothing():
    update_snapshot_health_metrics()

    assert not SnapshotHealthMetric.objects.exists()


@pytest.mark.django_db
@patch("apps.metagraph.tasks._SNAPSHOT_HEALTH_WINDOWS", {"72m": 361, "144m": 722})
@override_settings(METAGRAPH_NETUIDS=[])
def test_dumpable_blocks_are_counted_correctly(latest_block, neuron):
    # Insert all but three of the expected snapshots within the wider window
    dumpable_blocks = get_dumpable_blocks_in_range(
        latest_block.number - 722, latest_block.number - 361, neuron.subnet_id
    )
    for bnum in sorted(dumpable_blocks)[:-3]:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))
    # Insert all expected snapshots within the smaller window
    dumpable_blocks = get_dumpable_blocks_in_range(latest_block.number - 361, latest_block.number, neuron.subnet_id)
    for bnum in sorted(dumpable_blocks):
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))

    update_snapshot_health_metrics()

    row = SnapshotHealthMetric.objects.get(netuid=neuron.subnet_id, window="72m")
    assert row.missing_blocks == 0
    row = SnapshotHealthMetric.objects.get(netuid=neuron.subnet_id, window="144m")
    assert row.missing_blocks == 3


@pytest.mark.django_db
@patch("apps.metagraph.tasks._SNAPSHOT_HEALTH_WINDOWS", {"72m": 361})
@override_settings(METAGRAPH_NETUIDS=[])
def test_partially_missing_snapshots_are_disregarded(latest_block, neuron, other_neuron):
    """
    The snapshot health metric logic only checks if there is at least one NeuronSnapshot for each
    expected block and will still count partially missing snapshots as a healthy dump
    """
    # Insert all but three of the expected snapshots of one neuron
    dumpable_blocks = get_dumpable_blocks_in_range(latest_block.number - 361, latest_block.number, neuron.subnet_id)
    for bnum in sorted(dumpable_blocks)[:-3]:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))
    # Insert all expected snapshots of the other neuron
    dumpable_blocks = get_dumpable_blocks_in_range(
        latest_block.number - 361, latest_block.number, other_neuron.subnet_id
    )
    for bnum in sorted(dumpable_blocks):
        NeuronSnapshotFactory(neuron=other_neuron, block=BlockFactory(number=bnum))

    update_snapshot_health_metrics()

    row = SnapshotHealthMetric.objects.get(netuid=neuron.subnet_id, window="72m")
    assert row.missing_blocks == 0


@pytest.mark.django_db
@patch("apps.metagraph.tasks._SNAPSHOT_HEALTH_WINDOWS", {"72m": 361})
@override_settings(METAGRAPH_NETUIDS=[])
def test_snapshots_at_non_dumpable_blocks_do_not_affect_missing_count(latest_block, neuron):
    """
    Snapshots stored at blocks that are not dumpable for the subnet must neither
    count as coverage for a dumpable block nor otherwise change the missing count.
    """
    dumpable_blocks = get_dumpable_blocks_in_range(latest_block.number - 361, latest_block.number, neuron.subnet_id)
    # Cover all dumpable blocks except three.
    for bnum in sorted(dumpable_blocks)[:-3]:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))
    # Add snapshots at in-window blocks that are NOT dumpable for this subnet.
    non_dumpable = [
        bnum for bnum in range(latest_block.number - 361, latest_block.number + 1) if bnum not in dumpable_blocks
    ][:5]
    assert non_dumpable, "test setup: expected non-dumpable blocks inside the window"
    for bnum in non_dumpable:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))

    update_snapshot_health_metrics()

    row = SnapshotHealthMetric.objects.get(netuid=neuron.subnet_id, window="72m")
    assert row.missing_blocks == 3


@pytest.mark.django_db
@patch("apps.metagraph.tasks._SNAPSHOT_HEALTH_WINDOWS", {"72m": 361})
@override_settings(METAGRAPH_NETUIDS=[])
def test_task_replaces_previous_rows(latest_block, neuron):
    # A stale row that should be removed on the next run.
    SnapshotHealthMetric.objects.create(netuid=999, window="72m", missing_blocks=7)

    update_snapshot_health_metrics()

    assert not SnapshotHealthMetric.objects.filter(netuid=999).exists()
    assert SnapshotHealthMetric.objects.filter(netuid=neuron.subnet_id, window="72m").exists()


@pytest.mark.django_db
def test_metrics_exposes_persisted_snapshot_health_rows(client):
    SnapshotHealthMetric.objects.create(netuid=5, window="7d", missing_blocks=4)
    SnapshotHealthMetric.objects.create(netuid=5, window="12d", missing_blocks=9)
    SnapshotHealthMetric.objects.create(netuid=15, window="7d", missing_blocks=1)
    SnapshotHealthMetric.objects.create(netuid=15, window="12d", missing_blocks=12)

    content = client.get("/metrics").content.decode()
    assert _gauge_value(content, 5, "7d") == 4.0
    assert _gauge_value(content, 5, "12d") == 9.0
    assert _gauge_value(content, 15, "7d") == 1.0
    assert _gauge_value(content, 15, "12d") == 12.0


@pytest.mark.django_db
def test_metrics_clears_stale_snapshot_health_labels(client):
    SnapshotHealthMetric.objects.create(netuid=5, window="7d", missing_blocks=4)

    # Replace the persisted rows, mirroring a fresh task run, and re-publish.
    SnapshotHealthMetric.objects.all().delete()
    SnapshotHealthMetric.objects.create(netuid=6, window="7d", missing_blocks=1)

    content = client.get("/metrics").content.decode()
    assert _gauge_value(content, 6, "7d") == 1.0
    with pytest.raises(KeyError):
        _gauge_value(content, 5, "7d")


@pytest.mark.django_db
def test_snapshot_health_metric_recovers_after_backfill(client):
    row = SnapshotHealthMetric.objects.create(netuid=5, window="7d", missing_blocks=8)
    assert _gauge_value(client.get("/metrics").content.decode(), 5, "7d") == 8
    row.missing_blocks = 0
    row.save()
    assert _gauge_value(client.get("/metrics").content.decode(), 5, "7d") == 0


@pytest.mark.django_db
@override_settings(METAGRAPH_NETUIDS=[1, 2], METAGRAPH_SNAPSHOT_HEALTH_START_BLOCK=99753)
def test_collection_start_limits_windows_without_hiding_later_gaps(client):
    BlockFactory(number=100000, timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    neuron = NeuronFactory(subnet=SubnetFactory(netuid=1))
    # Subnet 1 expects 99753, 99873, 99993, 99994 from this boundary.
    # Leave the boundary itself and 99873 missing, including on a later run.
    for number in (99993, 99994):
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=number))

    update_snapshot_health_metrics()
    content = client.get("/metrics").content.decode()
    for window in ("7d", "12d"):
        assert _gauge_value(content, 1, window) == 2
        # Subnet 2 has no snapshots at all; its three expected blocks still count.
        assert _gauge_value(content, 2, window) == 3

    # Older backfilled rows must not change when coverage became expected.
    NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=99000))
    update_snapshot_health_metrics()
    assert _gauge_value(client.get("/metrics").content.decode(), 1, "7d") == 2

    for number in (99753, 99873):
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=number))
    update_snapshot_health_metrics()
    assert _gauge_value(client.get("/metrics").content.decode(), 1, "7d") == 0


@pytest.mark.django_db
@pytest.mark.parametrize("start_block", [0, 10000])
def test_established_collection_keeps_full_rolling_windows(settings, client, start_block):
    settings.METAGRAPH_NETUIDS = [1]
    settings.METAGRAPH_SNAPSHOT_HEALTH_START_BLOCK = start_block
    BlockFactory(number=100000, timestamp=datetime(2026, 1, 1, tzinfo=UTC))

    update_snapshot_health_metrics()

    content = client.get("/metrics").content.decode()
    # 7d begins at 49600: two tail slots + 139 full epochs + one start slot.
    assert _gauge_value(content, 1, "7d") == 559
    # 12d begins at 13600: one tail slot + 239 full epochs + one start slot.
    assert _gauge_value(content, 1, "12d") == 958


@pytest.mark.django_db
@pytest.mark.parametrize("start_block", [-1, 100001])
def test_invalid_collection_start_preserves_previous_health_result(settings, start_block):
    settings.METAGRAPH_NETUIDS = [1]
    settings.METAGRAPH_SNAPSHOT_HEALTH_START_BLOCK = start_block
    BlockFactory(number=100000, timestamp=datetime(2026, 1, 1, tzinfo=UTC))
    SnapshotHealthMetric.objects.create(netuid=1, window="7d", missing_blocks=5)

    with pytest.raises(ValueError, match="METAGRAPH_SNAPSHOT_HEALTH_START_BLOCK"):
        update_snapshot_health_metrics()

    assert SnapshotHealthMetric.objects.get(netuid=1, window="7d").missing_blocks == 5
