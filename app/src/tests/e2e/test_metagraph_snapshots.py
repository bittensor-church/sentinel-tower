"""E2E: a real metagraph snapshot is stored and browsable through the explorer.

Covers the analyst snapshot story (§2.1) and the admin Metagraph Explorer stories
(§3.1, §3.2), driving the real `bittensor` provider's metagraph path end to end.

Scope notes (see QA.md):
- The localnet's subnet 1 carries one neuron and no weights/bonds, so the lite-vs-full
  distinction (§2.3) is not observable here — that is left to the sync-service unit tests.
- APY (§2.4) needs multi-epoch dividend history the localnet does not accrue; the APY
  view is unit-tested (tests/metagraph/test_apy_epoch_view.py).
"""

from __future__ import annotations

import pytest

from apps.metagraph.block_tasks import sync_metagraph_for_block
from apps.metagraph.models import Block, MetagraphDump, Neuron, NeuronSnapshot, Subnet

from .conftest import GENESIS_NETUID, Localnet

pytestmark = pytest.mark.django_db


@pytest.fixture
def expected_hotkey() -> str:
    return "5C4hrfjw9DjXZTzV3MwzrrAr9P1MJhSrvWGWqi1eSuyUpnhM"


@pytest.fixture
def synced_block(localnet: Localnet) -> int:
    """Sync subnet 1's real metagraph at a recent block (recent to dodge state pruning).

    Returns the block number that was dumped.
    """
    # A couple of blocks back from head is safely inside the state-pruning window while
    # still being a settled block.
    block_number = localnet.head() - 2
    stats = sync_metagraph_for_block(block_number, GENESIS_NETUID, localnet.provider, lite=False)
    assert stats is not None, "expected the localnet to return a metagraph for subnet 1"
    return block_number


def test_metagraph_snapshot_is_persisted(localnet: Localnet, synced_block: int, expected_hotkey: str) -> None:
    """§2.1 — a real snapshot lands as queryable Subnet / Block / Neuron / NeuronSnapshot rows."""
    assert Subnet.objects.filter(netuid=GENESIS_NETUID).exists()
    assert Block.objects.filter(number=synced_block).exists()

    neurons = Neuron.objects.filter(subnet_id=GENESIS_NETUID)
    assert neurons.exists(), "expected at least one neuron on subnet 1"

    snapshots = NeuronSnapshot.objects.filter(block_id=synced_block, neuron__subnet_id=GENESIS_NETUID)
    assert snapshots.count() == neurons.count() == 1
    snap = snapshots.select_related("neuron__hotkey").first()
    assert snap is not None
    assert snap.neuron.hotkey.hotkey == expected_hotkey


def test_explorer_lists_only_dumped_blocks(localnet: Localnet, synced_block: int, admin_client) -> None:
    """§3.2 — the block selector offers the dumped block, and only blocks that were dumped."""
    response = admin_client.get(
        "/admin/metagraph/explorer/api/blocks/",
        {"subnet_id": str(GENESIS_NETUID)},
    )
    assert response.status_code == 200

    returned_blocks = {b["number"] for b in response.json()["blocks"]}
    dumped_blocks = set(MetagraphDump.objects.filter(netuid=GENESIS_NETUID).values_list("block__number", flat=True))

    assert synced_block in returned_blocks
    # The explorer must not offer blocks that were never dumped.
    assert returned_blocks == dumped_blocks


def test_explorer_returns_metagraph_state_for_a_block(
    localnet: Localnet, synced_block: int, admin_client, expected_hotkey: str
) -> None:
    """§3.1 — picking a subnet + block returns that subnet's full metagraph state."""
    response = admin_client.get(
        "/admin/metagraph/explorer/api/data/",
        {"subnet_id": str(GENESIS_NETUID), "block_number": str(synced_block)},
    )
    assert response.status_code == 200

    payload = response.json()
    stored_snapshots = NeuronSnapshot.objects.filter(block_id=synced_block, neuron__subnet_id=GENESIS_NETUID)
    assert payload["summary"]["total_neurons"] == stored_snapshots.count()
    assert payload["neurons"], "expected neuron rows in the explorer response"
    assert len(payload["neurons"])
    assert payload["neurons"][0]["hotkey_full"] == expected_hotkey
