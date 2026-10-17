"""E2E: a subnet registered through a real 2-of-2 multisig is alerted on execution only.

Proves the SDK decodes a real ``Multisig.as_multi`` (the nested call and the
``MultisigExecuted`` event) into the shape the unwrapping relies on. Discord is
stubbed at the transport seam; everything above it is the real pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

import bittensor as bt
import pytest
from bittensor.sp_core import Keypair

from ._helpers import ingest_blocks
from .conftest import CapturedWebhooks, Localnet, SubmittedExtrinsic

pytestmark = pytest.mark.django_db

ONE_MILLION_TAO_IN_RAO = 1_000_000_000_000_000
MAX_WEIGHT = {"ref_time": 20_000_000_000, "proof_size": 500_000}


@dataclass
class MultisigRegistration:
    proposal: SubmittedExtrinsic
    execution: SubmittedExtrinsic
    multisig: str
    approver: str


def _new_multisig_account(localnet: Localnet, proposal: SubmittedExtrinsic) -> str:
    """The multisig account, as the chain reports it in the proposal's NewMultisig event."""
    block_hash = localnet.provider.get_block_hash(proposal.block_number)
    assert block_hash is not None
    for event in localnet.provider.get_events(block_hash):
        if event.get("extrinsic_idx") == proposal.index and event.get("event_id") == "NewMultisig":
            return str(event["attributes"]["multisig"])
    raise AssertionError(f"no NewMultisig event for {proposal.block_number}-{proposal.index}")


@pytest.fixture(scope="module")
def multisig_registration(localnet: Localnet, _funded_sudo: None) -> MultisigRegistration:
    """Alice proposes register_network from the Alice+Bob 2-of-2 multisig; Bob executes it.

    A fresh hotkey per run keeps the call hash unique, so a proposal left pending
    by an aborted run cannot collide with this one.
    """
    alice, bob = localnet.sudo_keypair, localnet.secondary_keypair
    hotkey = Keypair.create_from_mnemonic(Keypair.generate_mnemonic())
    inner = localnet.subtensor.compose(
        localnet.compose("SubtensorModule", "register_network", {"hotkey": hotkey.ss58_address})
    )

    proposal = localnet.submit(
        bt.calls.Multisig.as_multi(
            threshold=2,
            other_signatories=[bob.ss58_address],
            maybe_timepoint=None,
            call=inner,
            max_weight=MAX_WEIGHT,
        ),
        keypair=alice,
    )
    assert proposal.success is True
    multisig = _new_multisig_account(localnet, proposal)

    # The multisig pays the lock cost; Bob pays the execution fee.
    localnet.submit_sudo("Balances", "force_set_balance", {"who": multisig, "new_free": ONE_MILLION_TAO_IN_RAO})
    localnet.fund(bob, ONE_MILLION_TAO_IN_RAO)

    execution = localnet.submit(
        bt.calls.Multisig.as_multi(
            threshold=2,
            other_signatories=[alice.ss58_address],
            maybe_timepoint={"height": proposal.block_number, "index": proposal.index},
            call=inner,
            max_weight=MAX_WEIGHT,
        ),
        keypair=bob,
    )
    assert execution.success is True
    return MultisigRegistration(proposal=proposal, execution=execution, multisig=multisig, approver=bob.ss58_address)


def test_multisig_proposal_is_not_alerted(
    localnet: Localnet,
    multisig_registration: MultisigRegistration,
    discord_webhooks: dict[str, str],
    captured_webhooks: CapturedWebhooks,
) -> None:
    ingest_blocks(localnet, [multisig_registration.proposal.block_number])

    assert captured_webhooks.contents_for(discord_webhooks["subnet_registration"]) == []
    assert captured_webhooks.contents_for(discord_webhooks["sudo"]) == []


def test_multisig_execution_alerts_the_registration_with_the_multisig_as_actor(
    localnet: Localnet,
    multisig_registration: MultisigRegistration,
    discord_webhooks: dict[str, str],
    captured_webhooks: CapturedWebhooks,
) -> None:
    execution = multisig_registration.execution
    ingest_blocks(localnet, [execution.block_number])

    [content] = captured_webhooks.contents_for(discord_webhooks["subnet_registration"])
    heading = f"**Subnet {execution.netuid}**" if execution.netuid is not None else "**Pending netuid**"
    assert heading in content
    assert (
        f"**multisig**: `{multisig_registration.multisig}`\n**final approval**: `{multisig_registration.approver}`"
        in content
    )
    assert f"**hash**: `{execution.extrinsic_hash}`" in content
