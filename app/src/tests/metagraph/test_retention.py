"""Retention pruning for metagraph tables.

Policy (docs/superpowers/specs/2026-07-07-data-retention-design.md):
validator snapshots + their mechanism metrics survive forever; non-validator
snapshots (+ their metrics) at block_id <= snapshot cutoff are deleted;
weight/bond/collateral rows at block_id <= bulk cutoff are deleted.
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.metagraph import retention
from apps.metagraph.models import MechanismMetrics, NeuronSnapshot, Weight
from tests.factories.metagraph import (
    BlockFactory,
    BondFactory,
    CollateralFactory,
    MechanismMetricsFactory,
    MetagraphDumpFactory,
    NeuronSnapshotFactory,
    WeightFactory,
)

CUTOFF = 100
# For split-window tests: the snapshot window is longer than the bulk window,
# so its cutoff is an OLDER (lower-numbered) block.
SNAPSHOT_CUTOFF = 100
BULK_CUTOFF = 200


@pytest.fixture
def old_block():
    return BlockFactory(number=CUTOFF - 1)


@pytest.fixture
def new_block():
    return BlockFactory(number=CUTOFF + 1)


@pytest.mark.django_db
def test_prunes_old_nonvalidator_snapshots_and_their_metrics(old_block, new_block):
    old_miner = NeuronSnapshotFactory(block=old_block, is_validator=False)
    old_miner_mm = MechanismMetricsFactory(snapshot=old_miner)
    new_miner = NeuronSnapshotFactory(block=new_block, is_validator=False)

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)

    assert not NeuronSnapshot.objects.filter(pk=old_miner.pk).exists()
    assert not MechanismMetrics.objects.filter(pk=old_miner_mm.pk).exists()
    assert NeuronSnapshot.objects.filter(pk=new_miner.pk).exists()
    assert deleted["metagraph_neuron_snapshot"] == 1
    assert deleted["metagraph_mechanism_metrics"] == 1


@pytest.mark.django_db
def test_validator_snapshots_and_metrics_survive_any_age(old_block):
    validator = NeuronSnapshotFactory(block=old_block, is_validator=True)
    validator_mm = MechanismMetricsFactory(snapshot=validator)

    retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)

    assert NeuronSnapshot.objects.filter(pk=validator.pk).exists()
    assert MechanismMetrics.objects.filter(pk=validator_mm.pk).exists()


@pytest.mark.django_db
def test_prunes_old_weight_bond_collateral(old_block, new_block):
    old_rows = [
        WeightFactory(block=old_block),
        BondFactory(block=old_block),
        CollateralFactory(block=old_block),
    ]
    new_rows = [
        WeightFactory(block=new_block),
        BondFactory(block=new_block),
        CollateralFactory(block=new_block),
    ]

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)

    for row in old_rows:
        assert not type(row).objects.filter(pk=row.pk).exists()
    for row in new_rows:
        assert type(row).objects.filter(pk=row.pk).exists()
    assert deleted["metagraph_weight"] == 1
    assert deleted["metagraph_bond"] == 1
    assert deleted["metagraph_collateral"] == 1


@pytest.mark.django_db
def test_batching_deletes_everything_across_batches(old_block):
    for _ in range(5):
        NeuronSnapshotFactory(block=old_block, is_validator=False)

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=2)

    assert deleted["metagraph_neuron_snapshot"] == 5
    assert not NeuronSnapshot.objects.filter(block=old_block, is_validator=False).exists()


@pytest.mark.django_db
def test_max_batches_caps_the_run(old_block):
    for _ in range(5):
        WeightFactory(block=old_block)

    deleted = retention.prune_expired(
        snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=2, max_batches=1
    )

    # one batch of 2 per table at most
    assert deleted["metagraph_weight"] == 2
    assert Weight.objects.filter(block=old_block).count() == 3


@pytest.mark.django_db
def test_dry_run_counts_without_deleting(old_block):
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)
    MechanismMetricsFactory(snapshot=snapshot)
    WeightFactory(block=old_block)

    counted = retention.prune_expired(
        snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10, dry_run=True
    )

    assert counted["metagraph_neuron_snapshot"] == 1
    assert counted["metagraph_mechanism_metrics"] == 1
    assert counted["metagraph_weight"] == 1
    assert NeuronSnapshot.objects.filter(pk=snapshot.pk).exists()
    assert Weight.objects.exists()


@pytest.mark.django_db
def test_snapshot_with_multiple_mechanism_metrics(old_block):
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)
    MechanismMetricsFactory(snapshot=snapshot, mech_id=0)
    MechanismMetricsFactory(snapshot=snapshot, mech_id=1)

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)

    assert deleted["metagraph_neuron_snapshot"] == 1
    assert deleted["metagraph_mechanism_metrics"] == 2
    assert not MechanismMetrics.objects.exists()


@pytest.mark.django_db
def test_noop_when_nothing_below_cutoff(new_block):
    NeuronSnapshotFactory(block=new_block, is_validator=False)

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)

    assert all(count == 0 for count in deleted.values())


def test_rejects_nonpositive_batch_size():
    with pytest.raises(ValueError):
        retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=0)


@pytest.mark.django_db
def test_split_windows_prune_each_table_group_by_its_own_cutoff():
    # Three block ages: older than both windows, between the windows (older
    # than the bulk window only), newer than both windows.
    oldest = BlockFactory(number=SNAPSHOT_CUTOFF - 1)
    between = BlockFactory(number=SNAPSHOT_CUTOFF + 50)
    newest = BlockFactory(number=BULK_CUTOFF + 1)

    oldest_weight = WeightFactory(block=oldest)
    oldest_miner = NeuronSnapshotFactory(block=oldest, is_validator=False)
    between_weight = WeightFactory(block=between)
    between_miner = NeuronSnapshotFactory(block=between, is_validator=False)
    newest_weight = WeightFactory(block=newest)
    newest_miner = NeuronSnapshotFactory(block=newest, is_validator=False)

    deleted = retention.prune_expired(
        snapshot_cutoff_block=SNAPSHOT_CUTOFF, bulk_cutoff_block=BULK_CUTOFF, batch_size=10
    )

    # weights follow the (shorter) bulk window
    assert not Weight.objects.filter(pk=oldest_weight.pk).exists()
    assert not Weight.objects.filter(pk=between_weight.pk).exists()
    assert Weight.objects.filter(pk=newest_weight.pk).exists()
    # a non-validator snapshot the same age as the deleted between_weight
    # survives, because the snapshot window is longer
    assert not NeuronSnapshot.objects.filter(pk=oldest_miner.pk).exists()
    assert NeuronSnapshot.objects.filter(pk=between_miner.pk).exists()
    assert NeuronSnapshot.objects.filter(pk=newest_miner.pk).exists()
    assert deleted["metagraph_weight"] == 2
    assert deleted["metagraph_neuron_snapshot"] == 1


@pytest.mark.django_db
def test_none_snapshot_cutoff_skips_snapshot_tables(old_block):
    miner = NeuronSnapshotFactory(block=old_block, is_validator=False)
    weight = WeightFactory(block=old_block)

    deleted = retention.prune_expired(snapshot_cutoff_block=None, bulk_cutoff_block=CUTOFF, batch_size=10)

    assert NeuronSnapshot.objects.filter(pk=miner.pk).exists()
    assert not Weight.objects.filter(pk=weight.pk).exists()
    assert deleted["metagraph_neuron_snapshot"] == 0
    assert deleted["metagraph_mechanism_metrics"] == 0
    assert deleted["metagraph_weight"] == 1


@pytest.mark.django_db
def test_none_bulk_cutoff_skips_bulk_tables(old_block):
    miner = NeuronSnapshotFactory(block=old_block, is_validator=False)
    weight = WeightFactory(block=old_block)

    deleted = retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=None, batch_size=10)

    assert not NeuronSnapshot.objects.filter(pk=miner.pk).exists()
    assert Weight.objects.filter(pk=weight.pk).exists()
    assert deleted["metagraph_neuron_snapshot"] == 1
    assert deleted["metagraph_weight"] == 0
    assert deleted["metagraph_bond"] == 0
    assert deleted["metagraph_collateral"] == 0


@pytest.mark.django_db
def test_dry_run_with_none_cutoffs_counts_zero_for_skipped_tables(old_block):
    NeuronSnapshotFactory(block=old_block, is_validator=False)
    WeightFactory(block=old_block)

    counted = retention.prune_expired(snapshot_cutoff_block=None, bulk_cutoff_block=CUTOFF, batch_size=10, dry_run=True)

    assert counted["metagraph_neuron_snapshot"] == 0
    assert counted["metagraph_mechanism_metrics"] == 0
    assert counted["metagraph_weight"] == 1
    assert NeuronSnapshot.objects.exists()
    assert Weight.objects.exists()


def _refresh_and_fetch_views() -> tuple[list, list]:
    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW mv_validator_apy_windows")
        cursor.execute("REFRESH MATERIALIZED VIEW mv_subnet_validator_apy_epochs")
        cursor.execute("SELECT * FROM mv_validator_apy_windows")
        windows = sorted(cursor.fetchall())
        cursor.execute("SELECT * FROM mv_subnet_validator_apy_epochs")
        epochs = sorted(cursor.fetchall())
    return windows, epochs


@pytest.mark.django_db
def test_apy_views_identical_before_and_after_prune(old_block, new_block):
    # The fixtures' Faker timestamps can fall outside the views' time windows;
    # pin them so both views see the blocks (retention prunes by block NUMBER,
    # so old_block stays prune-eligible regardless of its timestamp).
    old_block.timestamp = timezone.now() - timedelta(days=1)
    old_block.save(update_fields=["timestamp"])
    new_block.timestamp = timezone.now()
    new_block.save(update_fields=["timestamp"])

    # validator data old enough to be prune-eligible if the policy were wrong,
    # seeded to satisfy both views' filters (alpha_stake/alpha_dividends > 0,
    # end-of-epoch dump row) so they emit real rows.
    validator = NeuronSnapshotFactory(
        block=old_block,
        is_validator=True,
        alpha_stake=10**12,
        alpha_dividends=10**9,
    )
    MechanismMetricsFactory(snapshot=validator, dividend=0.5)
    MetagraphDumpFactory(netuid=validator.neuron.subnet_id, block=old_block, epoch_position=2)
    # non-validator noise that SHOULD be pruned
    miner = NeuronSnapshotFactory(block=old_block, is_validator=False)
    MechanismMetricsFactory(snapshot=miner)

    before = _refresh_and_fetch_views()
    retention.prune_expired(snapshot_cutoff_block=CUTOFF, bulk_cutoff_block=CUTOFF, batch_size=10)
    after = _refresh_and_fetch_views()

    assert all(before), "both views should emit rows for the seeded validator"
    assert before == after
