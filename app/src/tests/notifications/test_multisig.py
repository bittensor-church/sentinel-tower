"""Multisig-wrapped calls reach the same notifications as direct ones.

Drives the real registry and handlers through ``dispatch_block_notifications``;
Discord is stubbed at the transport seam (``channels._http_client``).
Extrinsic shapes are the ones the ingestion parser produced for finney blocks
9155226 (multisig proposal) and 9155237 (its execution).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from apps.extrinsics.hyperparam_service import enrich_extrinsics_with_previous_values
from apps.extrinsics.models import SubnetHyperparam, SubnetHyperparamHistory
from apps.notifications import channels, dispatch_block_notifications

MULTISIG = "5GGrRdUatgDLiJxnytdWfYCwsAb1Cyo4U5Dw1HmLiAcbWj88"
PROPOSER = "5DcvgrRijwUtKYNCQ7ULqC5NzVYXA99t7HApoAwKLBVUZRvA"
FINAL_APPROVER = "5HEZQ7GwMZSBsXJr6GQWsifwTawm81LxDSB7PZBtvHYfgLYt"
THIRD_SIGNATORY = "5H64k2fFMVAxGYxzmQoT66rS3BW1RhLM692QULgDLYdMjkh9"
HOTKEY = "5Hn6PHyjx2rLY3EXCP1xK7XHUquRo17fyuyM1HuZrAWb8y3G"
INNER_CALL_HASH = "0x10c3e822a374f30d14d85bc35388db905dfee64a23847ae74a6177fa9ae64d55"
EXECUTION_HASH = "0xa2c676a10cea44eb21e9172c848d83eb95a9f6ac4cc3a2c45e37a437b32ba898"

# Dev accounts //Alice and //Bob and their 1-of-2 multisig, as reported by a
# real localnet (System.Remarked sender of an as_multi_threshold_1 call).
ALICE = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"
BOB = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUspZC92UhjJM694ty"
ALICE_BOB_THRESHOLD_1 = "5DnowFkXHuvv5PwXAedoneD7SKmci7WRkfpS2izURzCrBCxj"

REGISTRATION_URL = "https://discord.test/webhooks/subnet-registration"
SUDO_URL = "https://discord.test/webhooks/sudo"
ADMIN_UTILS_URL = "https://discord.test/webhooks/admin-utils"

REGISTER_NETWORK_CALL: dict[str, Any] = {
    "call_index": "0x073b",
    "call_function": "register_network",
    "call_module": "SubtensorModule",
    "call_args": [{"name": "hotkey", "type": "AccountId", "value": HOTKEY}],
    "call_hash": INNER_CALL_HASH,
}


def _event(module_id: str, event_id: str, attributes: Any) -> dict[str, Any]:
    return {"module_id": module_id, "event_id": event_id, "attributes": attributes}


def _as_multi(call: dict[str, Any], *, address: str, others: list[str], timepoint: Any, events: list) -> dict:
    return {
        "extrinsic_hash": EXECUTION_HASH,
        "block_number": 9155237,
        "extrinsic_index": 2,
        "call_module": "Multisig",
        "call_function": "as_multi",
        "call_args": [
            {"name": "threshold", "type": "u16", "value": 2},
            {"name": "other_signatories", "type": "Vec<AccountId>", "value": others},
            {"name": "maybe_timepoint", "type": "Option<Timepoint<BlockNumberFor>>", "value": timepoint},
            {"name": "call", "type": "RuntimeCall", "value": call},
            {"name": "max_weight", "type": "Weight", "value": {"ref_time": 6743682000, "proof_size": 18677}},
        ],
        "address": address,
        "success": True,
        "status": "success",
        "events": events,
        "netuid": None,
    }


def _executed(call: dict[str, Any] = REGISTER_NETWORK_CALL, *, result: Any = None, call_hash: str = INNER_CALL_HASH):
    """Finney 9155237-0002: the final approval that executed register_network."""
    return _as_multi(
        call,
        address=FINAL_APPROVER,
        others=[PROPOSER, THIRD_SIGNATORY],
        timepoint={"height": 9155226, "index": 7},
        events=[
            _event("Balances", "Unreserved", {"who": PROPOSER, "amount": 196000000}),
            _event("SubtensorModule", "NetworkRemoved", 82),
            _event("Balances", "Locked", {"who": MULTISIG, "amount": 628711951616}),
            _event(
                "SubtensorModule",
                "NetworkRegistrationQueued",
                {
                    "coldkey": MULTISIG,
                    "hotkey": HOTKEY,
                    "mechid": 1,
                    "identity": None,
                    "lock_amount": 628711951616,
                    "median_subnet_alpha_price": {"bits": 81942628773116384},
                    "registration_block": 9155237,
                },
            ),
            _event(
                "Multisig",
                "MultisigExecuted",
                {
                    "approving": FINAL_APPROVER,
                    "timepoint": {"height": 9155226, "index": 7},
                    "multisig": MULTISIG,
                    "call_hash": call_hash,
                    "result": result if result is not None else {"Ok": []},
                },
            ),
            _event("System", "ExtrinsicSuccess", {}),
        ],
    )


def _proposed() -> dict[str, Any]:
    """Finney 9155226-0007: the first approval; the call is carried but not executed."""
    return {
        **_as_multi(
            REGISTER_NETWORK_CALL,
            address=PROPOSER,
            others=[THIRD_SIGNATORY, FINAL_APPROVER],
            timepoint=None,
            events=[
                _event("Balances", "Reserved", {"who": PROPOSER, "amount": 196000000}),
                _event(
                    "Multisig",
                    "NewMultisig",
                    {"approving": PROPOSER, "multisig": MULTISIG, "call_hash": INNER_CALL_HASH},
                ),
                _event("System", "ExtrinsicSuccess", {}),
            ],
        ),
        "extrinsic_hash": "0x34c473e90091e6f5547a37293f42cf80854f8ea7b863d68cadb5ec5877a2b234",
        "block_number": 9155226,
        "extrinsic_index": 7,
    }


def _sudo(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "call_index": "0x0300",
        "call_module": "Sudo",
        "call_function": "sudo",
        "call_args": [{"name": "call", "type": "RuntimeCall", "value": call}],
        "call_hash": "0x" + "ab" * 32,
    }


def _executed_sudo(inner: dict[str, Any]) -> dict[str, Any]:
    """A multisig executing a Sudo call (the sudo key held by a multisig)."""
    wrapped = _sudo(inner)
    return _executed(wrapped, call_hash=wrapped["call_hash"])


class _RecordingHTTPClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict | None = None, **_: Any) -> Any:
        self.posts.append((url, json or {}))
        return self

    def raise_for_status(self) -> None:
        return None

    def contents_for(self, url: str) -> list[str]:
        return [payload["content"] for posted_url, payload in self.posts if posted_url == url]


@pytest.fixture
def discord(monkeypatch: pytest.MonkeyPatch) -> _RecordingHTTPClient:
    client = _RecordingHTTPClient()
    monkeypatch.setattr(channels, "_http_client", client)
    monkeypatch.setenv("DISCORD_SUBNET_REGISTRATION_WEBHOOK_URL", REGISTRATION_URL)
    monkeypatch.setenv("DISCORD_SUDO_ALERTS_WEBHOOK_URL", SUDO_URL)
    monkeypatch.setenv("DISCORD_ADMIN_UTILS_ALERTS_WEBHOOK_URL", ADMIN_UTILS_URL)
    monkeypatch.setenv("DISCORD_COLDKEY_SWAP_WEBHOOK_URL", "")
    return client


def test_executed_multisig_registration_is_notified_with_the_multisig_as_actor(discord):
    count = dispatch_block_notifications(9155237, [_executed()])

    assert count == 1
    assert discord.contents_for(REGISTRATION_URL) == [
        "**Block #9155237**\n"
        "\n"
        "**Pending netuid**\n"
        "`register_network`\n"
        "**outcome**: queued — 628.711951616 TAO locked, alpha price snapshot 0.004442\n"
        "**pruned to make room**: subnet `82`\n"
        f"**multisig**: `{MULTISIG}`\n"
        f"**final approval**: `{FINAL_APPROVER}`\n"
        f"**hotkey**: `{HOTKEY}`\n"
        f"**hash**: `{EXECUTION_HASH}`\n"
        "\n"
        "[View on TaoStats](https://taostats.io/extrinsic/9155237-0002?network=finney)"
    ]
    assert [url for url, _ in discord.posts] == [REGISTRATION_URL]


def test_multisig_proposal_alone_is_not_notified(discord):
    assert dispatch_block_notifications(9155226, [_proposed()]) == 0
    assert discord.posts == []


def test_executed_multisig_whose_inner_call_failed_is_not_notified(discord):
    failed = _executed(result={"Err": {"Module": {"index": 7, "error": "0x2a000000"}}})

    assert dispatch_block_notifications(9155237, [failed]) == 0
    assert discord.posts == []


def test_proposal_and_execution_in_one_block_notify_once(discord):
    count = dispatch_block_notifications(9155237, [_proposed(), _executed()])

    assert count == 1
    assert len(discord.contents_for(REGISTRATION_URL)) == 1


def test_threshold_1_multisig_registration_is_notified(discord):
    ext = {
        **_executed(),
        "call_function": "as_multi_threshold_1",
        "call_args": [
            {"name": "other_signatories", "type": "Vec<AccountId>", "value": [BOB]},
            {"name": "call", "type": "RuntimeCall", "value": REGISTER_NETWORK_CALL},
        ],
        "address": ALICE,
        # Older runtimes emit no MultisigExecuted for threshold 1; the origin is derived.
        "events": [_event("SubtensorModule", "NetworkAdded", {"netuid": 129, "mechid": 1})],
    }

    assert dispatch_block_notifications(9155237, [ext]) == 1
    [content] = discord.contents_for(REGISTRATION_URL)
    assert "**Subnet 129**" in content
    assert "**outcome**: created — netuid `129`" in content
    assert f"**multisig**: `{ALICE_BOB_THRESHOLD_1}`\n**final approval**: `{ALICE}`" in content


def test_multisig_wrapped_call_without_a_handler_is_dropped(discord):
    remark = {"call_module": "System", "call_function": "remark", "call_args": [], "call_hash": "0x" + "cd" * 32}

    assert dispatch_block_notifications(9155237, [_executed(remark, call_hash=remark["call_hash"])]) == 0
    assert discord.posts == []


def test_multisig_wrapped_sudo_call_without_a_handler_reaches_the_sudo_catch_all(discord):
    remark = {"call_module": "System", "call_function": "remark", "call_args": [{"name": "remark", "value": "0x01"}]}

    assert dispatch_block_notifications(9155237, [_executed_sudo(remark)]) == 1
    assert discord.contents_for(SUDO_URL) == [
        "**Block #9155237**\n"
        "\n"
        "**Global**\n"
        "`remark` — **remark**: `0x01`\n"
        "\n"
        "[View on TaoStats](https://taostats.io/extrinsic/9155237-0002?network=finney)"
    ]
    assert discord.contents_for(REGISTRATION_URL) == []


@pytest.mark.django_db
def test_multisig_wrapped_sudo_hyperparam_change_records_and_notifies_previous_value(discord):
    set_tempo = {
        "call_module": "AdminUtils",
        "call_function": "sudo_set_tempo",
        "call_args": [{"name": "netuid", "value": 7}, {"name": "tempo", "value": 360}],
    }
    SubnetHyperparam.objects.create(netuid=7, param_name="tempo", value=99, last_block_number=9155236)

    enriched = enrich_extrinsics_with_previous_values([_executed_sudo(set_tempo)])
    count = dispatch_block_notifications(9155237, enriched)

    assert count == 1
    assert discord.contents_for(ADMIN_UTILS_URL) == [
        "**Block #9155237**\n"
        "\n"
        "**Subnet 7**\n"
        "**tempo**: `99` → `360`\n"
        "\n"
        "[View on TaoStats](https://taostats.io/extrinsic/9155237-0002?network=finney)"
    ]
    assert discord.contents_for(SUDO_URL) == []
    assert SubnetHyperparam.objects.get(netuid=7, param_name="tempo").value == 360
    history = SubnetHyperparamHistory.objects.get(netuid=7, param_name="tempo", block_number=9155237)
    assert (history.old_value, history.new_value, history.address) == (99, 360, MULTISIG)


def test_direct_and_sudo_wrapped_registrations_are_unchanged(discord):
    direct = {
        **copy.deepcopy(_executed()),
        "call_module": "SubtensorModule",
        "call_function": "register_network",
        "call_args": REGISTER_NETWORK_CALL["call_args"],
        "address": FINAL_APPROVER,
    }

    assert dispatch_block_notifications(9155237, [direct]) == 1
    [content] = discord.contents_for(REGISTRATION_URL)
    assert f"**signer**: `{FINAL_APPROVER}`" in content
    assert "**multisig**" not in content


def test_multisig_runtime_upgrade_alert_fits_in_a_discord_message(discord):
    """Finney 9286202-0028: the sudo multisig executing Sudo(System.set_code) with a ~2.6 MB wasm blob."""
    code = "0x52bc537646db8e05" + "00" * 2_645_806 + "b65d2039"
    set_code = {"call_module": "System", "call_function": "set_code", "call_args": [{"name": "code", "value": code}]}

    assert dispatch_block_notifications(9286202, [_executed_sudo(set_code)]) == 1
    [content] = discord.contents_for(SUDO_URL)
    assert content == (
        "**Block #9286202**\n"
        "\n"
        "**Global**\n"
        "`set_code` — **code**: `0x52bc537646db8e05…b65d2039 (2645818 bytes)`\n"
        "\n"
        "[View on TaoStats](https://taostats.io/extrinsic/9286202-0002?network=finney)"
    )
