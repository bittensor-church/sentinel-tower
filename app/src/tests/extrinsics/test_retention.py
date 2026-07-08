import pytest

from apps.extrinsics import retention
from apps.extrinsics.models import Extrinsic

CUTOFF = 100


def make_extrinsic(block_number: int, i: int) -> Extrinsic:
    return Extrinsic.objects.create(
        block_number=block_number,
        extrinsic_hash=f"0x{block_number:032x}{i:032x}",
        call_module="SubtensorModule",
        call_function="set_weights",
    )


@pytest.mark.django_db
def test_prunes_only_extrinsics_at_or_below_cutoff():
    old = make_extrinsic(CUTOFF - 1, 0)
    boundary = make_extrinsic(CUTOFF, 1)
    new = make_extrinsic(CUTOFF + 1, 2)

    deleted = retention.prune_expired(cutoff_block=CUTOFF, batch_size=10)

    assert deleted["extrinsics"] == 2
    assert not Extrinsic.objects.filter(pk=old.pk).exists()
    assert not Extrinsic.objects.filter(pk=boundary.pk).exists()
    assert Extrinsic.objects.filter(pk=new.pk).exists()


@pytest.mark.django_db
def test_dry_run_counts_without_deleting():
    make_extrinsic(CUTOFF - 1, 0)

    counted = retention.prune_expired(cutoff_block=CUTOFF, batch_size=10, dry_run=True)

    assert counted["extrinsics"] == 1
    assert Extrinsic.objects.count() == 1


@pytest.mark.django_db
def test_batching_and_max_batches():
    for i in range(5):
        make_extrinsic(CUTOFF - 1, i)

    deleted = retention.prune_expired(cutoff_block=CUTOFF, batch_size=2, max_batches=1)
    assert deleted["extrinsics"] == 2

    deleted = retention.prune_expired(cutoff_block=CUTOFF, batch_size=2)
    assert deleted["extrinsics"] == 3
    assert not Extrinsic.objects.exists()


def test_rejects_nonpositive_batch_size():
    with pytest.raises(ValueError):
        retention.prune_expired(cutoff_block=CUTOFF, batch_size=0)
