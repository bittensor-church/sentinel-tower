"""Tests for the per-epoch validator APY data points and materialized view."""

import pytest

from tests.factories.metagraph import NeuronSnapshotFactory, SubnetFactory


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
