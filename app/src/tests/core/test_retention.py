from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.metagraph.models import NeuronSnapshot, Weight
from project.core import retention
from tests.factories.metagraph import BlockFactory, NeuronSnapshotFactory, WeightFactory


@pytest.mark.django_db
def test_cutoff_is_newest_block_older_than_window():
    old = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    BlockFactory(number=15, timestamp=None)  # backfilled block, no timestamp

    assert retention.compute_cutoff_block(days=90) == old.number


@pytest.mark.django_db
def test_cutoff_none_when_nothing_expired():
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))

    assert retention.compute_cutoff_block(days=90) is None


def test_rejects_nonpositive_days():
    # No django_db marker: the guard fires before any DB access.
    with pytest.raises(ValueError):
        retention.run(days=0)


def test_rejects_nonpositive_bulk_days():
    # No django_db marker: the guard fires before any DB access.
    with pytest.raises(ValueError):
        retention.run(bulk_days=0)


@pytest.mark.django_db
def test_run_is_noop_without_cutoff():
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))

    result = retention.run(days=90, bulk_days=40)

    assert result == {"cutoff_block": None, "bulk_cutoff_block": None, "deleted": {}}


@pytest.mark.django_db
def test_run_prunes_both_apps_and_reports_counts():
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    NeuronSnapshotFactory(block=old_block, is_validator=False)

    result = retention.run(days=90, batch_size=10)

    assert result["cutoff_block"] == 10
    assert result["deleted"]["metagraph_neuron_snapshot"] == 1
    assert result["deleted"]["extrinsics"] == 0


@pytest.mark.django_db
def test_run_uses_separate_windows_per_table_group():
    oldest = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    between = BlockFactory(number=15, timestamp=timezone.now() - timedelta(days=50))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    old_miner = NeuronSnapshotFactory(block=oldest, is_validator=False)
    between_miner = NeuronSnapshotFactory(block=between, is_validator=False)
    between_weight = WeightFactory(block=between)

    result = retention.run(days=90, bulk_days=40, batch_size=10)

    assert result["cutoff_block"] == 10
    assert result["bulk_cutoff_block"] == 15
    # weight in the 40–90d gap is pruned by the bulk window …
    assert not Weight.objects.filter(pk=between_weight.pk).exists()
    # … while the same-age non-validator snapshot survives (90d window)
    assert NeuronSnapshot.objects.filter(pk=between_miner.pk).exists()
    assert not NeuronSnapshot.objects.filter(pk=old_miner.pk).exists()


@pytest.mark.django_db
def test_run_prunes_bulk_window_even_when_snapshot_window_is_empty():
    between = BlockFactory(number=15, timestamp=timezone.now() - timedelta(days=50))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    weight = WeightFactory(block=between)
    miner = NeuronSnapshotFactory(block=between, is_validator=False)

    result = retention.run(days=90, bulk_days=40, batch_size=10)

    assert result["cutoff_block"] is None
    assert result["bulk_cutoff_block"] == 15
    assert not Weight.objects.filter(pk=weight.pk).exists()
    assert NeuronSnapshot.objects.filter(pk=miner.pk).exists()
    assert result["deleted"]["metagraph_neuron_snapshot"] == 0
    assert result["deleted"]["extrinsics"] == 0


@pytest.mark.django_db
def test_run_dry_run_reports_both_windows():
    oldest = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    between = BlockFactory(number=15, timestamp=timezone.now() - timedelta(days=50))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    NeuronSnapshotFactory(block=oldest, is_validator=False)
    WeightFactory(block=between)

    result = retention.run(days=90, bulk_days=40, batch_size=10, dry_run=True)

    assert result["cutoff_block"] == 10
    assert result["bulk_cutoff_block"] == 15
    assert result["deleted"]["metagraph_neuron_snapshot"] == 1
    assert result["deleted"]["metagraph_weight"] == 1
    assert NeuronSnapshot.objects.exists()
    assert Weight.objects.exists()


@pytest.mark.django_db
def test_run_skips_when_lock_held(monkeypatch):
    # Postgres advisory locks are reentrant per session, and the test runs in
    # the same DB session as ``retention.run()``, so holding the real lock here
    # would not make the run's ``pg_try_advisory_lock`` fail (verified
    # empirically). Patch the acquisition helper instead to simulate another
    # session holding the lock.
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)

    monkeypatch.setattr(retention, "_try_advisory_lock", lambda cursor: False)

    result = retention.run(days=90, batch_size=10)

    assert result == {"cutoff_block": None, "bulk_cutoff_block": None, "deleted": {}, "skipped": "lock"}
    assert type(snapshot).objects.filter(pk=snapshot.pk).exists()


@pytest.mark.django_db
def test_command_dry_run_reports_and_deletes_nothing():
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)

    out = StringIO()
    call_command("prune_retention", "--dry-run", stdout=out)

    assert "Snapshot cutoff block: 10" in out.getvalue()
    assert "Bulk cutoff block: 10" in out.getvalue()
    assert "metagraph_neuron_snapshot: 1" in out.getvalue()
    assert type(snapshot).objects.filter(pk=snapshot.pk).exists()


@pytest.mark.django_db
def test_command_bulk_days_flag_narrows_the_bulk_window():
    between = BlockFactory(number=15, timestamp=timezone.now() - timedelta(days=50))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    weight = WeightFactory(block=between)

    out = StringIO()
    call_command("prune_retention", "--bulk-days", "40", "--batch-size", "10", stdout=out)

    assert "Snapshot cutoff block: none (window empty)" in out.getvalue()
    assert "Bulk cutoff block: 15" in out.getvalue()
    assert not Weight.objects.filter(pk=weight.pk).exists()


@pytest.mark.django_db
def test_command_prunes_for_real():
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)

    out = StringIO()
    call_command("prune_retention", "--batch-size", "10", stdout=out)

    assert not type(snapshot).objects.filter(pk=snapshot.pk).exists()


def test_command_keyboard_interrupt_exits_cleanly():
    out = StringIO()
    with patch.object(retention, "run", side_effect=KeyboardInterrupt):
        call_command("prune_retention", stdout=out)

    assert "Interrupted — committed batches are kept; re-run to resume." in out.getvalue()


def test_cleanup_task_calls_orchestrator():
    from project.core import tasks

    with patch.object(tasks.retention, "run", return_value={"cutoff_block": 1, "deleted": {}}) as run:
        tasks.cleanup_expired_data()

    run.assert_called_once_with()
