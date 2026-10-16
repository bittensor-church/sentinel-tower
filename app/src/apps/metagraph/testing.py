"""Test support: mock contacts for the metagraph app's external boundaries."""

from dataclasses import dataclass, field

from apps.metagraph.services.chain_identity import ChainIdentityContact


@dataclass
class MockChainIdentityContact(ChainIdentityContact):
    """Serves `identities` (coldkey -> registered name) as the chain's identity registry.

    Set `error` to make the next reads fail the way an unreachable node would.
    """

    identities: dict[str, str] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def get_coldkey_identity_names(self) -> dict[str, str]:
        self.calls.append("get_coldkey_identity_names")
        if self.error is not None:
            raise self.error
        return dict(self.identities)
