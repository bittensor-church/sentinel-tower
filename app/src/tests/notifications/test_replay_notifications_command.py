"""The replay_notifications command dry-runs the pipeline for a past block."""

from __future__ import annotations

from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from sentinel.v1.testing.providers import FakeBlockchainProvider

from apps.extrinsics.models import Extrinsic, SubnetHyperparam, SubnetHyperparamHistory
from apps.notifications import channels
from apps.notifications.management.commands import replay_notifications

pytestmark = pytest.mark.django_db

BLOCK = 9155237
MULTISIG = "5GGrRdUatgDLiJxnytdWfYCwsAb1Cyo4U5Dw1HmLiAcbWj88"
APPROVER = "5HEZQ7GwMZSBsXJr6GQWsifwTawm81LxDSB7PZBtvHYfgLYt"
HOTKEY = "5Hn6PHyjx2rLY3EXCP1xK7XHUquRo17fyuyM1HuZrAWb8y3G"
CALL_HASH = "0x10c3e822a374f30d14d85bc35388db905dfee64a23847ae74a6177fa9ae64d55"


def _event(index: int | None, module_id: str, event_id: str, attributes: Any) -> dict[str, Any]:
    phase = {"ApplyExtrinsic": index} if index is not None else "Finalization"
    return {
        "phase": phase,
        "extrinsic_idx": index,
        "event_index": "0x0000",
        "module_id": module_id,
        "event_id": event_id,
        "attributes": attributes,
        "topics": [],
    }


def _multisig_registration_block(provider: FakeBlockchainProvider) -> FakeBlockchainProvider:
    """Block 9155237 as the node serves it: a multisig executing register_network, plus a tempo change."""
    as_multi = {
        "index": 0,
        "extrinsic_hash": "0xa2c676a1",
        "call_module": "Multisig",
        "call_function": "as_multi",
        "call_args": [
            {"name": "threshold", "type": "u16", "value": 2},
            {"name": "other_signatories", "type": "Vec<AccountId>", "value": []},
            {"name": "maybe_timepoint", "type": "Option<Timepoint<BlockNumberFor>>", "value": None},
            {
                "name": "call",
                "type": "RuntimeCall",
                "value": {
                    "call_module": "SubtensorModule",
                    "call_function": "register_network",
                    "call_args": [{"name": "hotkey", "type": "AccountId", "value": HOTKEY}],
                    "call_hash": CALL_HASH,
                },
            },
        ],
        "address": APPROVER,
        "nonce": 0,
        "tip": 0,
    }
    set_tempo = {
        "index": 1,
        "extrinsic_hash": "0xtempo",
        "call_module": "Sudo",
        "call_function": "sudo",
        "call_args": [
            {
                "name": "call",
                "type": "RuntimeCall",
                "value": {
                    "call_module": "AdminUtils",
                    "call_function": "sudo_set_tempo",
                    "call_args": [{"name": "netuid", "value": 7}, {"name": "tempo", "value": 360}],
                },
            }
        ],
        "address": APPROVER,
        "nonce": 1,
        "tip": 0,
    }
    events = [
        _event(0, "SubtensorModule", "NetworkAdded", {"netuid": 82, "mechid": 1}),
        _event(
            0,
            "Multisig",
            "MultisigExecuted",
            {"approving": APPROVER, "multisig": MULTISIG, "call_hash": CALL_HASH, "result": {"Ok": []}},
        ),
        _event(0, "System", "ExtrinsicSuccess", {}),
        _event(1, "System", "ExtrinsicSuccess", {}),
        _event(None, "SubtensorModule", "NetworkDissolveCleanupCompleted", {"netuid": 81}),
    ]
    return (
        provider.with_block(BLOCK, "0xblock")
        .with_extrinsics("0xblock", [as_multi, set_tempo])
        .with_events("0xblock", events)
    )


class _UnreachableNode(FakeBlockchainProvider):
    def get_block_hash(self, block_number: int) -> str | None:
        raise ConnectionError("state pruned")


class _ForbiddenHTTPClient:
    def post(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("replay_notifications must not post to webhooks")


@pytest.fixture(autouse=True)
def _no_webhook_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(channels, "_http_client", _ForbiddenHTTPClient())
    monkeypatch.setenv("DISCORD_SUBNET_REGISTRATION_WEBHOOK_URL", "https://discord.test/webhooks/registration")
    monkeypatch.setenv("DISCORD_ADMIN_UTILS_ALERTS_WEBHOOK_URL", "")


def _use_providers(monkeypatch, *, live: FakeBlockchainProvider, archive: FakeBlockchainProvider) -> None:
    monkeypatch.setattr(replay_notifications, "bittensor_provider", lambda *a, **kw: live)
    monkeypatch.setattr(replay_notifications, "get_archive_provider", lambda *a, **kw: archive)


def test_replay_prints_payloads_without_posting_or_writing(monkeypatch):
    _use_providers(
        monkeypatch,
        live=_multisig_registration_block(FakeBlockchainProvider()),
        archive=_UnreachableNode(),
    )
    SubnetHyperparam.objects.create(netuid=7, param_name="tempo", value=99, last_block_number=BLOCK - 1)
    stdout = StringIO()

    call_command("replay_notifications", str(BLOCK), stdout=stdout, stderr=StringIO())

    assert stdout.getvalue() == (
        f"Block {BLOCK}: 2 extrinsics, 3 notification(s) — dry run, nothing posted\n"
        "\n"
        "→ DISCORD_ADMIN_UTILS_ALERTS_WEBHOOK_URL (no webhook configured)\n"
        f"**Block #{BLOCK}**\n"
        "\n"
        "**Subnet 7**\n"
        "**tempo**: `99` → `360`\n"
        "\n"
        f"[View on TaoStats](https://taostats.io/extrinsic/{BLOCK}-0001?network=finney)\n"
        "\n"
        "→ DISCORD_SUBNET_REGISTRATION_WEBHOOK_URL (1 webhook(s) configured)\n"
        f"**Block #{BLOCK}**\n"
        "\n"
        "**Subnet 82**\n"
        "`register_network`\n"
        "**outcome**: created — netuid `82`\n"
        f"**multisig**: `{MULTISIG}`\n"
        f"**final approval**: `{APPROVER}`\n"
        f"**hotkey**: `{HOTKEY}`\n"
        "**hash**: `0xa2c676a1`\n"
        "\n"
        f"[View on TaoStats](https://taostats.io/extrinsic/{BLOCK}-0000?network=finney)\n"
        "\n"
        "→ DISCORD_SUBNET_REGISTRATION_WEBHOOK_URL (1 webhook(s) configured)\n"
        f"**Block #{BLOCK}**\n"
        "\n"
        "**Subnet 81** — dissolution cleanup completed\n"
        "\n"
        f"[View on TaoStats](https://taostats.io/block/{BLOCK}?network=finney)\n"
        "\n"
    )
    assert Extrinsic.objects.count() == 0
    assert SubnetHyperparam.objects.get(netuid=7, param_name="tempo").value == 99
    assert SubnetHyperparamHistory.objects.count() == 0


def test_replay_falls_back_to_archive_when_live_node_cannot_serve_the_block(monkeypatch):
    _use_providers(
        monkeypatch,
        live=_UnreachableNode(),
        archive=_multisig_registration_block(FakeBlockchainProvider()),
    )
    stdout, stderr = StringIO(), StringIO()

    call_command("replay_notifications", str(BLOCK), stdout=stdout, stderr=stderr)

    assert stderr.getvalue() == f"Block {BLOCK}: live node failed (state pruned); trying archive\n"
    assert stdout.getvalue().startswith(f"Block {BLOCK}: 2 extrinsics, 3 notification(s) — dry run, nothing posted\n")


def test_replay_reads_archive_directly_when_asked(monkeypatch):
    _use_providers(
        monkeypatch,
        live=_UnreachableNode(),
        archive=_multisig_registration_block(FakeBlockchainProvider()),
    )
    stderr = StringIO()

    call_command("replay_notifications", str(BLOCK), "--archive", stdout=StringIO(), stderr=stderr)

    assert stderr.getvalue() == ""


def test_replay_of_an_unreadable_block_fails(monkeypatch):
    _use_providers(monkeypatch, live=FakeBlockchainProvider(), archive=FakeBlockchainProvider())

    with pytest.raises(CommandError, match=f"^Block {BLOCK} could not be read from the chain"):
        call_command("replay_notifications", str(BLOCK), stdout=StringIO(), stderr=StringIO())
