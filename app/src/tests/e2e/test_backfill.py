"""E2E: the backfill command detects and fills a real gap in ingested blocks.

Covers the chain-operator backfill story (§1.4): after a missed block, gap detection
finds the exact missing block range and refills it from the node.
"""

from __future__ import annotations

import pytest

from apps.extrinsics.management.commands.backfill_extrinsics import _find_missing_blocks
from apps.extrinsics.models import Extrinsic

from ._helpers import ingest_blocks
from .conftest import Localnet

pytestmark = pytest.mark.django_db


def test_backfill_detects_and_fills_the_missing_block(localnet: Localnet) -> None:
    """A gap left in the ingested range is detected precisely and refilled from the node."""
    head = localnet.head()
    # Three consecutive settled blocks; we will deliberately skip the middle one.
    first, missing, last = head - 4, head - 3, head - 2

    ingest_blocks(localnet, [first, last])
    assert set(Extrinsic.objects.filter(block_number__in=[first, last]).values_list("block_number", flat=True)) == {
        first,
        last,
    }, "expected both boundary blocks to persist at least one extrinsic"
    assert not Extrinsic.objects.filter(block_number=missing).exists()

    # Scan the exact [first, last] window: gap detection reports only the skipped block.
    assert _find_missing_blocks(lookback=last - first, head=last) == [missing]

    # Refilling the block from the live node closes the gap. `missing` is well inside the
    # live-provider window, so no archive node is needed.
    ingest_blocks(localnet, [missing])
    assert Extrinsic.objects.filter(block_number=missing).exists()

    assert _find_missing_blocks(lookback=last - first, head=last) == []
