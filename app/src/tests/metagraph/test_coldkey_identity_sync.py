"""The hourly beat task that copies on-chain identity names onto known coldkeys."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from bittensor.sp_core import Keypair

from apps.metagraph import tasks
from apps.metagraph.models import Coldkey
from apps.metagraph.testing import MockChainIdentityContact
from tests.factories.metagraph import ColdkeyFactory

ALICE = Keypair.create_from_uri("//Alice").ss58_address
BOB = Keypair.create_from_uri("//Bob").ss58_address
CHARLIE = Keypair.create_from_uri("//Charlie").ss58_address
DAVE = Keypair.create_from_uri("//Dave").ss58_address
EVE = Keypair.create_from_uri("//Eve").ss58_address
FERDIE = Keypair.create_from_uri("//Ferdie").ss58_address
CHARLIE_STASH = Keypair.create_from_uri("//Charlie//stash").ss58_address
DAVE_STASH = Keypair.create_from_uri("//Dave//stash").ss58_address


@pytest.fixture
def chain() -> Iterator[MockChainIdentityContact]:
    contact = MockChainIdentityContact()
    with patch("apps.metagraph.services.coldkey_identity_sync.chain_identity_contact", return_value=contact):
        yield contact


def identity_names() -> dict[str, str | None]:
    return dict(Coldkey.objects.values_list("coldkey", "identity_name"))


@pytest.mark.django_db
def test_registered_names_are_stored_on_known_coldkeys_only(chain):
    ColdkeyFactory(coldkey=ALICE)
    ColdkeyFactory(coldkey=BOB)
    chain.identities = {ALICE: "Yuma, a DCG Company", CHARLIE: "Not one of ours"}

    tasks.sync_coldkey_identities()

    assert identity_names() == {ALICE: "Yuma, a DCG Company", BOB: None}
    assert chain.calls == ["get_coldkey_identity_names"]


@pytest.mark.django_db
def test_renamed_and_removed_identities_are_followed(chain):
    ColdkeyFactory(coldkey=ALICE, identity_name="Old name")
    ColdkeyFactory(coldkey=BOB, identity_name="Gone from chain")
    ColdkeyFactory(coldkey=CHARLIE, identity_name="Unchanged")
    chain.identities = {ALICE: "New name", CHARLIE: "Unchanged"}

    with patch.object(tasks, "logger") as logger:
        tasks.sync_coldkey_identities()

    assert identity_names() == {ALICE: "New name", BOB: None, CHARLIE: "Unchanged"}
    logger.info.assert_called_once_with("Synced coldkey identity names", added=0, changed=1, cleared=1)


@pytest.mark.django_db
def test_unusable_names_are_skipped_without_affecting_the_others(chain):
    for coldkey in (ALICE, BOB, CHARLIE, DAVE, EVE, FERDIE, CHARLIE_STASH, DAVE_STASH):
        ColdkeyFactory(coldkey=coldkey)
    chain.identities = {
        ALICE: "   ",
        BOB: BOB[:36],  # the owner pasted their own address as the name
        CHARLIE: "Crucible\x00 Labs\n",
        DAVE: "x" * 300,
        EVE: "5",  # a real, if odd, name that happens to match the address' first character
        FERDIE: "Rhef",
        CHARLIE_STASH: "0x09cC765F40520Bce2ECe342806c56DeD191462d1",  # an EVM address as the name
        DAVE_STASH: ALICE,  # someone else's SS58 address as the name
    }

    tasks.sync_coldkey_identities()

    assert identity_names() == {
        ALICE: None,
        BOB: None,
        CHARLIE: "Crucible Labs",
        DAVE: "x" * 255,
        EVE: "5",
        FERDIE: "Rhef",
        CHARLIE_STASH: None,
        DAVE_STASH: None,
    }


@pytest.mark.django_db
def test_manual_labels_are_never_touched(chain):
    ColdkeyFactory(coldkey=ALICE, label="Foundation Validator")
    chain.identities = {ALICE: "Opentensor Foundation"}

    tasks.sync_coldkey_identities()

    assert Coldkey.objects.values_list("label", "identity_name").get() == (
        "Foundation Validator",
        "Opentensor Foundation",
    )


@pytest.mark.django_db
def test_an_unreachable_chain_fails_the_run_and_keeps_stored_names(chain):
    ColdkeyFactory(coldkey=ALICE, identity_name="Yuma, a DCG Company")
    chain.error = ConnectionError("node unreachable")

    with pytest.raises(ConnectionError):
        tasks.sync_coldkey_identities()

    assert identity_names() == {ALICE: "Yuma, a DCG Company"}

    chain.error = None
    chain.identities = {ALICE: "Yuma"}
    tasks.sync_coldkey_identities()

    assert identity_names() == {ALICE: "Yuma"}
