"""The real chain-identity contact, read against identities registered on the localnet."""

import os
import uuid

import bittensor as bt
import pytest

from apps.metagraph.services.chain_identity import SubtensorChainIdentityContact

from .conftest import Localnet


def _set_identity(chain: Localnet, name: str) -> None:
    submitted = chain.submit(
        chain.compose(
            "SubtensorModule",
            "set_identity",
            {
                "name": name,
                "url": "",
                "github_repo": "",
                "image": "",
                "discord": "",
                "description": "",
                "additional": "",
            },
        ),
    )
    assert submitted.success, f"set_identity({name!r}) failed on chain"


@pytest.fixture
def registered_owner(localnet: Localnet, _funded_sudo: None) -> Localnet:
    """The sudo coldkey owns a registered hotkey, which the chain requires before it accepts an identity."""
    owner = localnet.sudo_keypair.ss58_address
    hotkey = localnet.secondary_keypair.ss58_address
    if hotkey not in (localnet.subtensor.query(bt.storage.SubtensorModule.OwnedHotkeys, [owner]) or []):
        registration = localnet.submit(
            localnet.compose("SubtensorModule", "register_network", {"hotkey": hotkey}),
        )
        assert registration.success
    assert hotkey in localnet.subtensor.query(bt.storage.SubtensorModule.OwnedHotkeys, [owner])
    return localnet


def test_reads_the_current_registered_name_of_each_coldkey(registered_owner: Localnet):
    contact = SubtensorChainIdentityContact(os.environ["BITTENSOR_NETWORK"])
    owner = registered_owner.sudo_keypair.ss58_address
    first_name = f"Sentinel e2e {uuid.uuid4().hex[:8]}"
    second_name = f"Sentinel e2e {uuid.uuid4().hex[:8]}"

    _set_identity(registered_owner, first_name)
    first_read = contact.get_coldkey_identity_names()

    _set_identity(registered_owner, second_name)
    second_read = contact.get_coldkey_identity_names()

    assert first_read[owner] == first_name
    assert second_read[owner] == second_name
    # Every other identity on the shared chain is returned unchanged by the rename.
    assert {k: v for k, v in second_read.items() if k != owner} == {k: v for k, v in first_read.items() if k != owner}
    assert registered_owner.secondary_keypair.ss58_address not in second_read
