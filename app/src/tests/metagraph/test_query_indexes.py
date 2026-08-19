"""Index shape backing the incoming-weight dashboard panels (migration 0016).

The panels chart "which validators weighted this miner, over this time
window": equality on target_neuron_id and mech_id, range on block_id. Before
0016 no index led with target_neuron_id, so a 7-day panel seq-scanned all
137M weight rows on prod (136s). These tests pin the three schema facts that
keep that fix in place, because each can be silently undone from models.py.
"""

import pytest
from django.db import connection


def _indexes(table: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = %s", [table])
        return dict(cursor.fetchall())


@pytest.mark.django_db
def test_incoming_weight_index_is_ordered_for_range_scan_and_covering():
    indexes = _indexes("metagraph_weight")

    assert "idx_weight_target_mech_block" in indexes
    definition = indexes["idx_weight_target_mech_block"]

    # Equality columns first, range column last: all three become index
    # conditions. Any other order demotes block_id to a post-scan filter.
    key_columns, _, include_columns = definition.partition(" INCLUDE ")
    assert key_columns.endswith("(target_neuron_id, mech_id, block_id)")

    # The payload the panels select. Without it every matching row costs a
    # random heap read -- ~14k of them on a 30-day window.
    assert "source_neuron_id" in include_columns
    assert "weight" in include_columns


@pytest.mark.django_db
def test_snapshot_neuron_lookups_are_served_by_the_unique_constraint():
    indexes = _indexes("metagraph_neuron_snapshot")

    # Dropped as redundant -- only safe because unique_neuron_block leads
    # with the same column and so serves the same lookups and FK cascades.
    assert "metagraph_neuron_snapshot_neuron_id_75a757dc" not in indexes
    assert indexes["unique_neuron_block"].endswith("(neuron_id, block_id)")


@pytest.mark.django_db
def test_mechanism_metrics_snapshot_lookups_are_served_by_the_unique_constraint():
    indexes = _indexes("metagraph_mechanism_metrics")

    assert "metagraph_mechanism_metrics_snapshot_id_d4dc12fb" not in indexes
    assert indexes["unique_snapshot_mech"].endswith("(snapshot_id, mech_id)")
