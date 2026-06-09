"""Tests for the per-epoch validator APY data points and materialized view."""

import pytest
from django.db import connection
from django.utils import timezone
from sentinel.v1.services.apy import single_epoch_apy

from tests.factories.metagraph import (
    BlockFactory,
    MetagraphDumpFactory,
    NeuronFactory,
    NeuronSnapshotFactory,
    SubnetFactory,
)


@pytest.mark.django_db
def test_new_apy_columns_persist():
    subnet = SubnetFactory(tempo=360, moving_price=0.025)
    subnet.refresh_from_db()
    assert subnet.tempo == 360
    assert subnet.moving_price == pytest.approx(0.025)

    snap = NeuronSnapshotFactory(alpha_dividends=50_000_000, tao_dividends=1_000_000)
    snap.refresh_from_db()
    assert int(snap.alpha_dividends) == 50_000_000
    assert int(snap.tao_dividends) == 1_000_000


def _refresh_epoch_view() -> None:
    # REFRESH MATERIALIZED VIEW (without CONCURRENTLY) is fully transactional in
    # Postgres, so it sees this test transaction's own inserted rows.
    with connection.cursor() as cursor:
        cursor.execute("REFRESH MATERIALIZED VIEW mv_subnet_validator_apy_epochs;")


@pytest.mark.django_db
def test_epoch_view_apy_matches_sdk_formula():
    subnet = SubnetFactory(tempo=360)
    neuron = NeuronFactory(subnet=subnet, uid=1)
    block = BlockFactory(timestamp=timezone.now())
    NeuronSnapshotFactory(
        neuron=neuron,
        block=block,
        uid=1,
        is_validator=True,
        alpha_stake=1000 * 10**9,            # 1000 alpha in rao
        alpha_dividends=int(0.05 * 10**9),   # 0.05 alpha in rao
    )
    MetagraphDumpFactory(netuid=subnet.netuid, block=block, epoch_position=2)

    _refresh_epoch_view()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT apy_pct FROM mv_subnet_validator_apy_epochs WHERE neuron_id = %s",
            [neuron.id],
        )
        row = cursor.fetchone()

    assert row is not None
    expected = single_epoch_apy(0.05, 1000, 360)  # ~43.94
    assert float(row[0]) == pytest.approx(expected, rel=1e-6)


@pytest.mark.django_db
def test_epoch_view_dedups_to_one_row_per_epoch():
    subnet = SubnetFactory(tempo=360)
    neuron = NeuronFactory(subnet=subnet, uid=1)
    end_block = BlockFactory(timestamp=timezone.now())
    inside_block = BlockFactory(timestamp=timezone.now())

    for blk, pos in ((end_block, 2), (inside_block, 1)):
        NeuronSnapshotFactory(
            neuron=neuron, block=blk, uid=1, is_validator=True,
            alpha_stake=1000 * 10**9, alpha_dividends=int(0.05 * 10**9),
        )
        MetagraphDumpFactory(netuid=subnet.netuid, block=blk, epoch_position=pos)

    _refresh_epoch_view()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM mv_subnet_validator_apy_epochs WHERE neuron_id = %s",
            [neuron.id],
        )
        (count,) = cursor.fetchone()

    assert count == 1  # only the epoch_position = 2 (end) snapshot is kept


@pytest.mark.django_db
def test_epoch_view_emits_one_row_per_distinct_epoch():
    # A validator present at the end of two distinct epochs yields two
    # time-series points (one row per epoch_block), not a deduped single row.
    subnet = SubnetFactory(tempo=360)
    neuron = NeuronFactory(subnet=subnet, uid=1)

    for offset in (1000, 2000):  # two different end-of-epoch blocks
        block = BlockFactory(number=offset, timestamp=timezone.now())
        NeuronSnapshotFactory(
            neuron=neuron, block=block, uid=1, is_validator=True,
            alpha_stake=1000 * 10**9, alpha_dividends=int(0.05 * 10**9),
        )
        MetagraphDumpFactory(netuid=subnet.netuid, block=block, epoch_position=2)

    _refresh_epoch_view()

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM mv_subnet_validator_apy_epochs WHERE neuron_id = %s",
            [neuron.id],
        )
        (count,) = cursor.fetchone()

    assert count == 2


@pytest.mark.django_db
def test_epoch_view_excludes_zero_dividend_and_non_validator():
    subnet = SubnetFactory(tempo=360)
    block = BlockFactory(timestamp=timezone.now())

    zero_div = NeuronFactory(subnet=subnet, uid=1)
    NeuronSnapshotFactory(
        neuron=zero_div, block=block, uid=1, is_validator=True,
        alpha_stake=1000 * 10**9, alpha_dividends=0,
    )
    non_val = NeuronFactory(subnet=subnet, uid=2)
    NeuronSnapshotFactory(
        neuron=non_val, block=block, uid=2, is_validator=False,
        alpha_stake=1000 * 10**9, alpha_dividends=int(0.05 * 10**9),
    )
    MetagraphDumpFactory(netuid=subnet.netuid, block=block, epoch_position=2)

    _refresh_epoch_view()

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM mv_subnet_validator_apy_epochs")
        (count,) = cursor.fetchone()

    assert count == 0
