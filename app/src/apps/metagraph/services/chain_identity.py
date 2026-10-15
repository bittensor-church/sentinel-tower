"""Contact for the on-chain identity registry (SubtensorModule.IdentitiesV2).

Owners register a display name for their coldkey on chain; it is the name taostats
shows. This contact only reads the registry. Deciding which names are usable and
storing them is `coldkey_identity_sync`'s job.
"""

import abc
from typing import Any

import bittensor as bt
from django.conf import settings


class ChainIdentityContact(abc.ABC):
    @abc.abstractmethod
    def get_coldkey_identity_names(self) -> dict[str, str]:
        """Return the registered display name of every coldkey that has an identity, as stored on chain."""


class SubtensorChainIdentityContact(ChainIdentityContact):
    def __init__(self, network: str) -> None:
        self._network = network

    def get_coldkey_identity_names(self) -> dict[str, str]:
        with bt.Subtensor(network=self._network) as subtensor:
            entries = subtensor.query_map(bt.storage.SubtensorModule.IdentitiesV2)
            return {str(coldkey): _identity_name(identity) for coldkey, identity in entries}


def _identity_name(identity: Any) -> str:
    name = identity.get("name") if isinstance(identity, dict) else getattr(identity, "name", None)
    return name if isinstance(name, str) else ""


_contact_instance: ChainIdentityContact | None = None


def chain_identity_contact() -> ChainIdentityContact:
    global _contact_instance  # noqa: PLW0603
    if _contact_instance is None:
        _contact_instance = SubtensorChainIdentityContact(settings.BITTENSOR_NETWORK)
    return _contact_instance
