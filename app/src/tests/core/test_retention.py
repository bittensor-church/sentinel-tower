from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from project.core import retention
from tests.factories.metagraph import BlockFactory, NeuronSnapshotFactory


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


@pytest.mark.django_db
def test_run_is_noop_without_cutoff():
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))

    result = retention.run(days=90)

    assert result == {"cutoff_block": None, "deleted": {}}


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

    assert result == {"cutoff_block": None, "deleted": {}, "skipped": "lock"}
    assert type(snapshot).objects.filter(pk=snapshot.pk).exists()


@pytest.mark.django_db
def test_command_dry_run_reports_and_deletes_nothing():
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)

    out = StringIO()
    call_command("prune_retention", "--dry-run", stdout=out)

    assert "metagraph_neuron_snapshot: 1" in out.getvalue()
    assert type(snapshot).objects.filter(pk=snapshot.pk).exists()


@pytest.mark.django_db
def test_command_prunes_for_real():
    old_block = BlockFactory(number=10, timestamp=timezone.now() - timedelta(days=91))
    BlockFactory(number=20, timestamp=timezone.now() - timedelta(days=1))
    snapshot = NeuronSnapshotFactory(block=old_block, is_validator=False)

    out = StringIO()
    call_command("prune_retention", "--batch-size", "10", stdout=out)

    assert not type(snapshot).objects.filter(pk=snapshot.pk).exists()
