"""E2E: real extrinsics on the chain become queryable, correctly-decoded records.

Covers the Chain Operator ingestion stories (USER_STORIES §1) and the admin
extrinsic-browser story (§3.3), driving the real `bittensor` provider end to end.
"""

from __future__ import annotations

import pytest

from apps.extrinsics.models import Extrinsic, SubtensorErrorCode

from ._helpers import GovernanceBatch, ingest_blocks, submit_governance_batch
from .conftest import GENESIS_NETUID, Localnet

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module")
def governance_batch(localnet: Localnet, _funded_sudo: None) -> GovernanceBatch:
    """Submit the batch once for the whole module; tests re-ingest per function."""
    return submit_governance_batch(localnet, tempo_value=137)


def _lookup_error_name(extrinsic: Extrinsic) -> str | None:
    """Resolve an extrinsic's on-chain failure to a friendly name, the way the
    weight-setting dashboard's SQL join does (Module.index/error → SubtensorErrorCode)."""
    module = (extrinsic.error_data or {}).get("dispatch_error", {}).get("Module", {})
    if "index" not in module or "error" not in module:
        return None
    return (
        SubtensorErrorCode.objects.filter(pallet_index=module["index"], error_code=module["error"])
        .values_list("name", flat=True)
        .first()
    )


def test_every_extrinsic_in_a_block_is_recorded(localnet: Localnet, governance_batch: GovernanceBatch) -> None:
    """§1.1 — the full audit trail: each submitted extrinsic is stored with its call identity."""
    ingest_blocks(localnet, governance_batch.blocks)

    for submitted, module, function in [
        (governance_batch.tempo_change, "Sudo", "sudo"),
        (governance_batch.registration, "SubtensorModule", "register_network"),
        (governance_batch.generic_sudo, "Sudo", "sudo"),
        (governance_batch.failed, "SubtensorModule", "burned_register"),
    ]:
        stored = Extrinsic.objects.get(extrinsic_hash=submitted.extrinsic_hash)
        assert stored.block_number == submitted.block_number
        assert stored.call_module == module
        assert stored.call_function == function
        assert stored.success is submitted.success


def test_registration_netuid_is_extracted_from_events(localnet: Localnet, governance_batch: GovernanceBatch) -> None:
    """§1.1 — register_network carries no netuid arg; it must be recovered from NetworkAdded."""
    ingest_blocks(localnet, governance_batch.blocks)

    stored = Extrinsic.objects.get(extrinsic_hash=governance_batch.registration.extrinsic_hash)
    assert stored.success is True
    # The ingested netuid must equal the exact one the chain assigned (captured from the
    # NetworkAdded event at submit time), not merely "some subnet above genesis".
    assert governance_batch.registration.netuid is not None
    assert stored.netuid == governance_batch.registration.netuid
    assert stored.netuid > GENESIS_NETUID


def test_failed_extrinsic_decodes_to_the_runtime_error_name(
    localnet: Localnet, governance_batch: GovernanceBatch
) -> None:
    """§1.5 — a real failure decodes to the correct Error<T> name via the lookup table.

    Registering on netuid 999 fails with SubnetNotExists on runtime 424. This is the
    exact path the weight-setting dashboard uses, and it is what caught the 0010 seed
    being off-by-one (0x4c000000 mislabeled as TooManyUnrevealedCommits).
    """
    ingest_blocks(localnet, governance_batch.blocks)

    stored = Extrinsic.objects.get(extrinsic_hash=governance_batch.failed.extrinsic_hash)
    assert stored.success is False
    assert stored.error_data is not None

    module = stored.error_data["dispatch_error"]["Module"]
    assert module["index"] == 7  # SubtensorModule
    assert _lookup_error_name(stored) == "SubnetNotExists"


def test_admin_can_filter_extrinsics_by_module_and_success(
    localnet: Localnet, governance_batch: GovernanceBatch, admin_client
) -> None:
    """§3.3 — the operator browses/filters extrinsics in the Django admin changelist."""
    ingest_blocks(localnet, governance_batch.blocks)

    # The admin surface the operator actually uses: the extrinsics changelist, filtered.
    response = admin_client.get("/admin/extrinsics/extrinsic/", {"success__exact": "0"})
    assert response.status_code == 200

    changelist = response.context["cl"]
    returned = list(changelist.queryset)
    assert governance_batch.failed.extrinsic_hash in {e.extrinsic_hash for e in returned}
    assert all(e.success is False for e in returned)
