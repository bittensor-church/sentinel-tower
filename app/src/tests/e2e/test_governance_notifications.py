"""E2E: real governance extrinsics drive the notification pipeline correctly.

Covers the Subnet Owner / Governance Watcher stories (§4) and the Hyperparameter
Watcher stories (§5), from a real Sudo-wrapped extrinsic on the chain through handler
matching, sudo unwrapping, and per-channel Discord delivery. Discord is stubbed at the
transport seam; everything above it is the real dispatch path.
"""

from __future__ import annotations

import pytest

from apps.extrinsics.models import SubnetHyperparam, SubnetHyperparamHistory

from ._helpers import GovernanceBatch, ingest_blocks, submit_governance_batch
from .conftest import GENESIS_NETUID, CapturedWebhooks, Localnet

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def governance_batch(localnet: Localnet, _funded_sudo: None) -> GovernanceBatch:
    return submit_governance_batch(localnet, tempo_value=151)


def test_specific_handlers_route_each_extrinsic_to_its_own_channel(
    localnet: Localnet,
    governance_batch: GovernanceBatch,
    discord_webhooks: dict[str, str],
    captured_webhooks: CapturedWebhooks,
) -> None:
    """§4.1/§4.5/§4.7 — sudo-wrapped AdminUtils reaches the hyperparam channel (not the
    Sudo catch-all), registration reaches the registration channel, and a generic Sudo
    call with no specific handler falls through to the catch-all."""
    ingest_blocks(localnet, governance_batch.blocks)

    admin_utils_msgs = captured_webhooks.contents_for(discord_webhooks["admin_utils"])
    registration_msgs = captured_webhooks.contents_for(discord_webhooks["subnet_registration"])
    sudo_msgs = captured_webhooks.contents_for(discord_webhooks["sudo"])

    # The tempo change is Sudo-wrapped AdminUtils: it must be unwrapped and routed to
    # the hyperparam handler, and must NOT appear in the Sudo catch-all.
    assert any("tempo" in m for m in admin_utils_msgs)
    assert not any("tempo" in m for m in sudo_msgs)

    # Registration routed to its own channel, carrying the real registered subnet and hash.
    assert any(
        governance_batch.registration.extrinsic_hash in m and f"Subnet {governance_batch.registration.netuid}" in m
        for m in registration_msgs
    ), "expected the registration alert to name the registered subnet and its extrinsic hash"

    # The generic System.remark Sudo call has no specific handler → catch-all, and the
    # catch-all message must name the actual inner call (`remark`).
    assert any("remark" in m for m in sudo_msgs), "expected the generic Sudo call in the catch-all channel"


def test_hyperparam_change_records_previous_and_new_value(
    localnet: Localnet, governance_batch: GovernanceBatch
) -> None:
    """§5.1/§5.2/§5.3 — the tempo change updates the current-value table and appends a
    history row carrying old → new, so alerts and dashboards can show the delta."""
    # Seed a known prior value so the "old" side of the change is deterministic.
    SubnetHyperparam.objects.create(
        netuid=GENESIS_NETUID,
        param_name="tempo",
        value=99,
        last_block_number=governance_batch.tempo_change.block_number - 1,
    )

    ingest_blocks(localnet, governance_batch.blocks)

    current = SubnetHyperparam.objects.get(netuid=GENESIS_NETUID, param_name="tempo")
    assert current.value == governance_batch.tempo_value

    history = SubnetHyperparamHistory.objects.get(
        netuid=GENESIS_NETUID,
        param_name="tempo",
        block_number=governance_batch.tempo_change.block_number,
    )
    assert history.old_value == 99
    assert history.new_value == governance_batch.tempo_value


def test_failed_governance_extrinsic_is_not_notified(
    localnet: Localnet,
    governance_batch: GovernanceBatch,
    discord_webhooks: dict[str, str],
    captured_webhooks: CapturedWebhooks,
) -> None:
    """§4.6 — recipients are only paged for extrinsics that actually succeeded on-chain.

    `failed_handled` is a real AdminUtils hyperparam change that failed on-chain
    (BadOrigin) but *does* match the hyperparam handler — so the success filter is the
    only thing that can suppress it. Its block is ingested in isolation (no successful
    AdminUtils change to mask the result), so the hyperparam channel must stay empty.
    """
    assert governance_batch.failed_handled.success is False

    ingest_blocks(localnet, [governance_batch.failed_handled.block_number])

    assert captured_webhooks.contents_for(discord_webhooks["admin_utils"]) == []


def test_announced_coldkey_swap_is_alerted(
    localnet: Localnet,
    _funded_sudo: None,
    discord_webhooks: dict[str, str],
    captured_webhooks: CapturedWebhooks,
) -> None:
    """§4.2 — a real coldkey-swap announcement produces an alert on the central channel.

    Coldkey-swap extrinsics carry no netuid, so the handler resolves the signer's roles
    and always posts to the central coldkey-swap webhook. This proves the real
    announce_coldkey_swap extrinsic matches the handler and is delivered.

    An announcement locks the sudo account until it matures (~50 blocks, ~20s), so the
    cleanup waits for that before clearing — otherwise the lock leaks to later tests. The
    per-subnet webhook enable/disable toggle (§4.3/§4.4) is pure DB logic covered by unit
    tests in tests/notifications/test_channels.py; see QA.md.
    """
    swap = localnet.announce_coldkey_swap()
    try:
        assert swap.success is True

        ingest_blocks(localnet, [swap.block_number])

        coldkey_msgs = captured_webhooks.contents_for(discord_webhooks["coldkey_swap"])
        # The alert must name the announce action and the signer, not merely exist.
        signer = localnet.sudo_keypair.ss58_address
        assert any("Coldkey Swap Announced" in m and signer in m for m in coldkey_msgs), (
            "expected a coldkey-swap-announced alert naming the signer on the central channel"
        )
    finally:
        # Wait for the announcement to mature, then clear it so the sudo account is
        # unlocked for every other test on this shared chain.
        assert localnet.clear_coldkey_swap_announcement(wait=True), (
            "failed to clear the coldkey-swap announcement; the sudo account remains locked"
        )
