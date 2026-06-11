from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from django.test import RequestFactory

from apps.metagraph.utils import get_dumpable_blocks_in_range
from apps.metagraph.views import snapshot_health_view
from tests.factories.metagraph import BlockFactory, NeuronFactory, NeuronSnapshotFactory, SubnetFactory


def _metric_value(content: str, netuid: int, window: str) -> float:
    """Return the gauge value for the given netuid/window label pair."""
    for line in content.splitlines():
        if line.startswith("#"):
            continue
        if f'netuid="{netuid}"' in line and f'window="{window}"' in line:
            return float(line.split()[-1])
    raise KeyError(f"metric not found: netuid={netuid} window={window}")


@pytest.fixture()
def rf():
    return RequestFactory()


@pytest.fixture()
def latest_block():
    return BlockFactory(number=1000, timestamp=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.fixture()
def neuron():
    subnet = SubnetFactory(netuid=1)
    return NeuronFactory(subnet=subnet)


@pytest.mark.django_db
def test_no_latest_block_returns_empty_response(rf):
    response = snapshot_health_view(rf.get("/metagraph-snapshot-health"))

    assert response.status_code == 200
    assert response.content == b""


@pytest.mark.django_db
@patch("apps.metagraph.views._WINDOWS", {"72m": 361})
def test_all_dumpable_blocks_covered_reports_zero_missing(rf, latest_block, neuron):
    # Insert all expected snapshots within the window
    dumpable_blocks = get_dumpable_blocks_in_range(latest_block.number - 361, latest_block.number, neuron.subnet_id)
    for bnum in dumpable_blocks:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))

    response = snapshot_health_view(rf.get("/metagraph-snapshot-health"))

    assert response.status_code == 200
    assert _metric_value(response.content.decode(), neuron.subnet_id, "72m") == 0.0


@pytest.mark.django_db
@patch("apps.metagraph.views._WINDOWS", {"72m": 361})
def test_missing_dumpable_blocks_are_counted(rf, latest_block, neuron):
    # Insert some of the expected snapshots within the window
    dumpable_blocks = get_dumpable_blocks_in_range(latest_block.number - 361, latest_block.number, neuron.subnet_id)
    for bnum in dumpable_blocks[:-3]:
        NeuronSnapshotFactory(neuron=neuron, block=BlockFactory(number=bnum))

    response = snapshot_health_view(rf.get("/metagraph-snapshot-health"))

    assert _metric_value(response.content.decode(), neuron.subnet_id, "72m") == 3.0
