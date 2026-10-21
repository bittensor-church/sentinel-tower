"""Exercise automatic gap repair through the command, real DB and SDK ingestion."""

import signal
from datetime import UTC, datetime
from io import StringIO

import pytest
from django.core.management import call_command
from sentinel.v1.providers.metagraph import NeuronRecord, SubnetMetagraph
from sentinel.v1.testing.providers import FakeBlockchainProvider

from apps.metagraph.management.commands import backfill_metagraph
from apps.metagraph.models import MetagraphDump, NeuronSnapshot
from tests.factories.metagraph import BlockFactory, MetagraphDumpFactory

STAMP = datetime(2026, 10, 21, tzinfo=UTC)
pytestmark = pytest.mark.django_db(transaction=True)


class RepairProvider(FakeBlockchainProvider):
    def __init__(self, *, heads=(623,), failures=None, empty=None):
        super().__init__()
        self.heads = list(heads)
        self.failures = dict(failures or {})
        self.empty = dict(empty or {})
        self.requests = []
        self.opens = 0
        self.closes = 0

    def __enter__(self):
        self.opens += 1
        return self

    def close(self):
        self.closes += 1

    def get_current_block(self):
        if not self.heads:
            signal.raise_signal(signal.SIGTERM)
            return 623
        result = self.heads.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get_mechanism_count(self, netuid, block_number=None):
        self.requests.append((netuid, block_number))
        key = (netuid, block_number)
        if self.failures.get(key, 0):
            self.failures[key] -= 1
            raise TimeoutError("archive temporarily unavailable")
        if self.empty.get(key, 0):
            self.empty[key] -= 1
            return 0
        return 1

    def add_dump(self, netuid, block):
        graph = SubnetMetagraph(
            netuid=netuid,
            block=block,
            tempo=360,
            neurons=[
                NeuronRecord(
                    uid=0,
                    hotkey=f"validator-{netuid}",
                    coldkey=f"owner-{netuid}",
                    validator_permit=True,
                    alpha_stake=10,
                    total_stake=10,
                )
            ],
        )
        self.with_metagraph(graph, block).with_block_timestamp(block, STAMP)
        return self


@pytest.fixture(autouse=True)
def isolated_signals_and_settings(settings):
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    settings.METAGRAPH_NETUIDS = [1, 2, 3]
    settings.METAGRAPH_SUPERBURN_COLDKEY = ""
    yield
    for sig, handler in previous.items():
        signal.signal(sig, handler)


def seed_dump(netuid, block, *, complete=True):
    return MetagraphDumpFactory(
        netuid=netuid,
        block=BlockFactory(number=block, timestamp=STAMP),
        started_at=STAMP,
        finished_at=STAMP if complete else None,
    )


def run_repair(monkeypatch, head, archive, **options):
    monkeypatch.setattr(backfill_metagraph, "bittensor_provider", lambda: head)
    monkeypatch.setattr(backfill_metagraph, "get_archive_provider", lambda: archive)
    output = StringIO()
    options = {"lookback": 400, "rate_limit": 0, "settle_blocks": 25, **options}
    call_command("backfill_metagraph", stdout=output, **options)
    return output.getvalue()


@pytest.mark.parametrize("failure_kind", ["failures", "empty"])
def test_repeated_scan_repairs_partial_restart_gap_and_retries_bad_subnet(monkeypatch, failure_kind):
    """Netuid 2 fails first; netuid 1 is still repaired, then only 2 is retried."""
    existing = seed_dump(1, 478)
    seed_dump(2, 477)
    unfinished = seed_dump(2, 597, complete=False)
    archive = RepairProvider(**{failure_kind: {(2, 597): 1}}).add_dump(1, 598).add_dump(2, 597)
    head = RepairProvider(heads=(623, 623))

    run_repair(monkeypatch, head, archive, interval=0.001)

    assert set(MetagraphDump.objects.values_list("netuid", "block_id")) == {
        (1, 478),
        (1, 598),
        (2, 477),
        (2, 597),
    }
    assert set(NeuronSnapshot.objects.values_list("neuron__subnet_id", "block_id", "alpha_stake")) == {
        (1, 598, 10_000_000_000),
        (2, 597, 10_000_000_000),
    }
    existing.refresh_from_db()
    unfinished.refresh_from_db()
    assert existing.finished_at == STAMP
    assert unfinished.finished_at is not None
    assert archive.requests.count((1, 598)) == 1
    assert archive.requests.count((2, 597)) == 2
    assert archive.opens == archive.closes == 2


def test_repeat_mode_waits_for_first_collection_and_for_settle_window(monkeypatch):
    seed_dump(1, 478)
    archive = RepairProvider().add_dump(1, 598)
    head = RepairProvider(heads=(622, 623))

    run_repair(monkeypatch, head, archive, interval=0.001)

    # At 622 block 598 is too recent. At 623 it becomes eligible. Never fetch
    # block 358 (before collection began), nor subnets 2/3 (never collected).
    assert archive.requests == [(1, 598)]
    assert list(NeuronSnapshot.objects.values_list("block_id", flat=True)) == [598]


def test_repeat_mode_recovers_after_head_connection_failure(monkeypatch):
    seed_dump(1, 478)
    archive = RepairProvider().add_dump(1, 598)
    head = RepairProvider(heads=(TimeoutError("head unavailable"), 623))

    run_repair(monkeypatch, head, archive, interval=0.001)

    assert list(NeuronSnapshot.objects.values_list("block_id", flat=True)) == [598]
    assert head.opens == head.closes == 3


def test_one_shot_still_backfills_before_first_dump_and_exits(monkeypatch, settings):
    settings.METAGRAPH_NETUIDS = [1]
    archive = RepairProvider().add_dump(1, 358).add_dump(1, 478).add_dump(1, 598)

    run_repair(monkeypatch, RepairProvider(), archive)

    assert list(NeuronSnapshot.objects.order_by("block_id").values_list("block_id", flat=True)) == [358, 478, 598]
    assert archive.closes == 1


def test_repeat_mode_bounds_repair_to_lookback_window(monkeypatch):
    seed_dump(1, 358)
    archive = RepairProvider().add_dump(1, 598)

    run_repair(monkeypatch, RepairProvider(), archive, interval=0.001, lookback=100)

    assert archive.requests == [(1, 598)]
    assert set(MetagraphDump.objects.values_list("block_id", flat=True)) == {358, 598}


def test_empty_installation_does_not_open_archive_or_backfill_history(monkeypatch):
    archive = RepairProvider()

    run_repair(monkeypatch, RepairProvider(), archive, interval=0.001)

    assert archive.opens == 0
    assert MetagraphDump.objects.count() == 0


def test_repeat_mode_retries_an_archive_handshake_failure(monkeypatch):
    class InitiallyUnreachableArchive(RepairProvider):
        def __enter__(self):
            if self.opens == 0:
                self.opens += 1
                raise TimeoutError("archive handshake unavailable")
            return super().__enter__()

    seed_dump(1, 478)
    archive = InitiallyUnreachableArchive().add_dump(1, 598)

    run_repair(monkeypatch, RepairProvider(heads=(623, 623)), archive, interval=0.001)

    assert list(NeuronSnapshot.objects.values_list("block_id", flat=True)) == [598]
    assert archive.opens == 2


def test_one_shot_preserves_default_safety_margin(monkeypatch, settings):
    settings.METAGRAPH_NETUIDS = [1]
    archive = RepairProvider().add_dump(1, 358).add_dump(1, 478)

    run_repair(monkeypatch, RepairProvider(heads=(778,)), archive, settle_blocks=300)

    assert list(NeuronSnapshot.objects.order_by("block_id").values_list("block_id", flat=True)) == [358, 478]
