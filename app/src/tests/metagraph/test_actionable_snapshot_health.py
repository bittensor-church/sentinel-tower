from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.metagraph.models import MetagraphDump, NeuronSnapshot, SnapshotHealthMetric
from apps.metagraph.retention import prune_expired
from apps.metagraph.tasks import update_snapshot_health_metrics
from tests.factories.metagraph import BlockFactory, NeuronFactory, NeuronSnapshotFactory, SubnetFactory


@pytest.fixture
def coverage(settings):
    settings.METAGRAPH_NETUIDS = [1]
    settings.METAGRAPH_SNAPSHOT_HEALTH_START_BLOCK = 99753
    settings.DATA_RETENTION_BATCH_SLEEP_SECONDS = 0
    now = datetime(2026, 10, 26, tzinfo=UTC)
    BlockFactory(number=100000, timestamp=now)
    neuron = NeuronFactory(subnet=SubnetFactory(netuid=1))
    # Four expected points. The first two deliberately have no snapshots.
    for number in (99753, 99873, 99993, 99994):
        block = BlockFactory(number=number, timestamp=now)
        if number >= 99993:
            NeuronSnapshotFactory(neuron=neuron, block=block, is_validator=False)
    return neuron


@pytest.mark.django_db
@pytest.mark.parametrize(
    "validator_count,finished,expected", [(0, True, 2), (1, True, 3), (None, True, 3), (0, False, 3)]
)
def test_retention_excludes_only_proven_cleanup(coverage, validator_count, finished, expected):
    now = datetime(2026, 10, 26, tzinfo=UTC)
    dump = MetagraphDump.objects.create(
        netuid=1, block_id=99993, validator_snapshot_count=validator_count, finished_at=now if finished else None
    )
    prune_expired(99993, None, batch_size=1)
    update_snapshot_health_metrics()
    row = SnapshotHealthMetric.objects.get(netuid=1, window="7d")
    assert row.missing_blocks == expected
    assert row.actionable_blocks == expected
    dump.refresh_from_db()
    assert (dump.retention_pruned_at is not None) == (expected == 2)


@pytest.mark.django_db
def test_partial_retention_batch_does_not_prove_empty_dump(coverage):
    other = NeuronFactory(subnet=coverage.subnet)
    NeuronSnapshotFactory(neuron=other, block_id=99993, is_validator=False)
    dump = MetagraphDump.objects.create(
        netuid=1, block_id=99993, validator_snapshot_count=0, finished_at=datetime(2026, 10, 26, tzinfo=UTC)
    )
    prune_expired(99993, None, batch_size=1, max_batches=1)
    dump.refresh_from_db()
    assert dump.retention_pruned_at is None
    prune_expired(99993, None, batch_size=1)
    dump.refresh_from_db()
    assert dump.retention_pruned_at is not None


@pytest.mark.django_db
def test_acknowledgement_is_exact_reversible_and_does_not_hide_new_gaps(coverage, client):
    from apps.metagraph.models import SnapshotGapAcknowledgement

    call_command(
        "acknowledge_snapshot_gap",
        block=99753,
        netuids=[1],
        reason="upstream_unavailable",
        evidence="Both archive responses returned no data at this exact block.",
    )
    update_snapshot_health_metrics()
    row = SnapshotHealthMetric.objects.get(netuid=1, window="7d")
    assert (row.missing_blocks, row.acknowledged_blocks, row.actionable_blocks) == (2, 1, 1)
    assert SnapshotGapAcknowledgement.objects.get(netuid=1, block_number=99753).evidence.startswith("Both archive")
    NeuronSnapshot.objects.filter(block_id=99994).delete()
    update_snapshot_health_metrics()
    row = SnapshotHealthMetric.objects.get(netuid=1, window="7d")
    assert (row.missing_blocks, row.acknowledged_blocks, row.actionable_blocks) == (3, 1, 2)
    content = client.get("/metrics").content.decode()
    assert 'metagraph_actionable_missing_snapshot_blocks{netuid="1",window="7d"} 2.0' in content
    call_command("acknowledge_snapshot_gap", block=99753, netuids=[1], revoke=True)
    update_snapshot_health_metrics()
    row = SnapshotHealthMetric.objects.get(netuid=1, window="7d")
    assert (row.missing_blocks, row.acknowledged_blocks, row.actionable_blocks) == (3, 0, 3)


@pytest.mark.django_db
def test_repaired_acknowledgement_cannot_hide_later_data_loss(coverage):
    from apps.metagraph.models import SnapshotGapAcknowledgement

    call_command(
        "acknowledge_snapshot_gap", block=99753, netuids=[1], reason="upstream_unavailable", evidence="Archive check"
    )
    NeuronSnapshotFactory(neuron=coverage, block_id=99753)
    update_snapshot_health_metrics()
    assert not SnapshotGapAcknowledgement.objects.filter(netuid=1, block_number=99753, revoked_at__isnull=True).exists()
    NeuronSnapshot.objects.filter(block_id=99753).delete()
    update_snapshot_health_metrics()
    row = SnapshotHealthMetric.objects.get(netuid=1, window="7d")
    assert row.actionable_blocks == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kwargs",
    [
        {"block": 99753, "netuids": [1], "reason": "upstream_unavailable"},
        {"block": 99994, "netuids": [1], "reason": "upstream_unavailable", "evidence": "Check"},
        {"block": 100354, "netuids": [1], "reason": "upstream_unavailable", "evidence": "Future gap"},
        {"block": 99753, "netuids": [999], "reason": "upstream_unavailable", "evidence": "Check"},
    ],
)
def test_acknowledgement_rejects_missing_evidence_or_wrong_scope(coverage, kwargs):
    with pytest.raises(CommandError):
        call_command("acknowledge_snapshot_gap", **kwargs)
