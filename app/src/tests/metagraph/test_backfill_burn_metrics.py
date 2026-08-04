"""Public-API tests for the burn metrics backfill command."""

from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from sentinel.v1.testing.providers import FakeBlockchainProvider

from apps.metagraph.models import MetaEpoch, SubnetBurn
from apps.metagraph.services.burn_service import BurnService
from apps.metagraph.utils import get_epoch_containing_block
from tests.factories.metagraph import (
    BlockFactory,
    ColdkeyFactory,
    HotkeyFactory,
    MechanismMetricsFactory,
    NeuronFactory,
    NeuronSnapshotFactory,
    SubnetFactory,
)

SOURCE_TIMESTAMP = datetime(2026, 8, 3, 13, 0, tzinfo=UTC)


def _epoch_start(netuid: int) -> int:
    return get_epoch_containing_block(8_760_000, netuid).start


def _stored_owner_incentive(netuid: int, block_number: int, timestamp: datetime | None) -> None:
    owner = ColdkeyFactory(coldkey="5BackfillOwner")
    subnet = SubnetFactory(netuid=netuid, owner_hotkey=HotkeyFactory(coldkey=owner))
    snapshot = NeuronSnapshotFactory(
        neuron=NeuronFactory(subnet=subnet, hotkey=HotkeyFactory(coldkey=owner)),
        block=BlockFactory(number=block_number, timestamp=timestamp),
    )
    MechanismMetricsFactory(snapshot=snapshot, mech_id=0, incentive=0.3)


@pytest.mark.django_db
def test_backfill_writes_burn_against_the_ingested_anchor(settings):
    settings.METAGRAPH_SUPERBURN_COLDKEY = ""
    netuid = 7
    block_number = _epoch_start(netuid)
    BlockFactory(number=BurnService.meta_epoch_block(block_number), timestamp=SOURCE_TIMESTAMP)
    _stored_owner_incentive(netuid, block_number, SOURCE_TIMESTAMP)
    stdout = StringIO()

    call_command(
        "backfill_burn_metrics",
        from_block=block_number,
        to_block=block_number,
        netuids=[netuid],
        stdout=stdout,
    )

    burn = SubnetBurn.objects.get()
    assert burn.subnet_id == netuid
    assert burn.source_block_number == block_number
    assert burn.burn == pytest.approx(0.3)
    assert burn.superburn == pytest.approx(0.0)
    assert burn.meta_epoch.block_id == BurnService.meta_epoch_block(block_number)
    assert burn.meta_epoch.block.timestamp == SOURCE_TIMESTAMP
    assert "Burn backfill complete: 1 rows" in stdout.getvalue()


@pytest.mark.django_db
def test_backfill_uses_the_ingested_anchor_when_the_snapshot_timestamp_is_missing():
    netuid = 7
    block_number = _epoch_start(netuid)
    anchor = BurnService.meta_epoch_block(block_number)
    BlockFactory(number=anchor, timestamp=SOURCE_TIMESTAMP)
    _stored_owner_incentive(netuid, block_number, None)
    stdout = StringIO()

    call_command(
        "backfill_burn_metrics",
        from_block=block_number,
        to_block=block_number,
        netuids=[netuid],
        stdout=stdout,
    )

    burn = SubnetBurn.objects.get()
    assert burn.meta_epoch.block_id == anchor
    assert burn.meta_epoch.block.timestamp == SOURCE_TIMESTAMP
    assert MetaEpoch.objects.count() == 1
    assert "Burn backfill complete: 1 rows" in stdout.getvalue()


@pytest.mark.django_db
def test_backfill_recovers_a_missing_anchor_from_the_archive(settings, monkeypatch):
    settings.METAGRAPH_SUPERBURN_COLDKEY = ""
    netuid = 7
    block_number = _epoch_start(netuid)
    anchor = BurnService.meta_epoch_block(block_number)
    _stored_owner_incentive(netuid, block_number, None)
    archive = FakeBlockchainProvider().with_block_timestamp(anchor, SOURCE_TIMESTAMP)
    monkeypatch.setattr("apps.metagraph.services.burn_service.get_archive_provider", lambda: archive)
    stdout = StringIO()

    call_command(
        "backfill_burn_metrics",
        from_block=block_number,
        to_block=block_number,
        netuids=[netuid],
        stdout=stdout,
    )

    burn = SubnetBurn.objects.get()
    recovered = burn.meta_epoch.block
    assert recovered.number == anchor
    assert recovered.timestamp == SOURCE_TIMESTAMP
    assert recovered.dump_started_at is None
    assert recovered.dump_finished_at is None
    assert "Burn backfill complete: 1 rows" in stdout.getvalue()
