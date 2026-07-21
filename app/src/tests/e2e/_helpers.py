"""Shared helpers for e2e tests: submit real extrinsics, ingest the resulting blocks."""

from __future__ import annotations

from dataclasses import dataclass

from apps.extrinsics.block_tasks import store_block_extrinsics
from apps.extrinsics.models import Extrinsic

from .conftest import GENESIS_NETUID, Localnet, SubmittedExtrinsic


@dataclass
class GovernanceBatch:
    """A batch of real extrinsics submitted to the chain, with where each landed.

    Submitted once (chain writes are slow and append-only); each test re-ingests the
    blocks into a fresh, transaction-isolated database.
    """

    tempo_change: SubmittedExtrinsic
    tempo_value: int
    registration: SubmittedExtrinsic
    generic_sudo: SubmittedExtrinsic
    failed: SubmittedExtrinsic
    # A failed extrinsic that *does* match a notification handler (unlike `failed`),
    # so §4.6's success filter has something to actually suppress. Kept out of `all`/
    # `blocks` so it is ingested only by the test that exercises the filter in isolation.
    failed_handled: SubmittedExtrinsic

    @property
    def all(self) -> list[SubmittedExtrinsic]:
        return [self.tempo_change, self.registration, self.generic_sudo, self.failed]

    @property
    def blocks(self) -> list[int]:
        return sorted({e.block_number for e in self.all})


def submit_governance_batch(chain: Localnet, tempo_value: int) -> GovernanceBatch:
    """Submit the representative governance extrinsics the notification system cares about.

    - a Sudo-wrapped AdminUtils hyperparam change (specific handler + hyperparam history)
    - a subnet registration (specific handler, netuid parsed from the NetworkAdded event)
    - a generic Sudo call with no specific handler (the Sudo catch-all)
    - a *failed* extrinsic with no handler (on-chain error decoding)
    - a *failed* extrinsic that matches a handler (proves the success filter suppresses it)
    """
    tempo_change = chain.submit_sudo("AdminUtils", "sudo_set_tempo", {"netuid": GENESIS_NETUID, "tempo": tempo_value})

    # Register a new subnet. Bob is the hotkey, Alice the coldkey/signer — this avoids
    # NonAssociatedColdKey when the hotkey is already tied to a different coldkey.
    registration = chain.submit(
        chain.compose("SubtensorModule", "register_network", {"hotkey": chain.secondary_keypair.ss58_address}),
    )

    # A Sudo call with no dedicated handler: schedule a no-op via System.remark.
    generic_sudo = chain.submit_sudo("System", "remark", {"remark": "0x53656e74696e656c"})

    # burned_register on a non-existent subnet is included but fails on-chain with a
    # decodable Module error (SubnetNotExists on runtime 424).
    failed = chain.submit(
        chain.compose(
            "SubtensorModule",
            "burned_register",
            {"netuid": 999, "hotkey": chain.sudo_keypair.ss58_address},
        ),
    )

    # A hyperparam change that DOES match the AdminUtils handler but fails on-chain:
    # AdminUtils calls require root, so submitting one directly (not via Sudo) is
    # included-but-failed with BadOrigin. A Sudo-wrapped failure would not do — the outer
    # sudo extrinsic still succeeds, so its recorded success would be True.
    failed_handled = chain.submit(
        chain.compose("AdminUtils", "sudo_set_tempo", {"netuid": GENESIS_NETUID, "tempo": tempo_value}),
    )

    return GovernanceBatch(
        tempo_change=tempo_change,
        tempo_value=tempo_value,
        registration=registration,
        generic_sudo=generic_sudo,
        failed=failed,
        failed_handled=failed_handled,
    )


def ingest_blocks(chain: Localnet, block_numbers: list[int]) -> int:
    """Ingest each block through the real pipeline. Returns total extrinsics stored."""
    before = Extrinsic.objects.count()
    for block_number in block_numbers:
        store_block_extrinsics(block_number, chain.provider)
    return Extrinsic.objects.count() - before
