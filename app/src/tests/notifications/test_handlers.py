"""Tests for concrete notification handlers (format_message output)."""

import pytest

from apps.notifications.handlers.admin_utils import AdminUtilsNotification
from apps.notifications.handlers.coldkey_swap import ColdkeySwapNotification
from apps.notifications.handlers.subnet_dissolution import SubnetDissolutionNotification
from apps.notifications.handlers.subnet_registration import SubnetRegistrationNotification
from apps.notifications.handlers.sudo import SudoNotification


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def admin_handler():
    return AdminUtilsNotification()


@pytest.fixture
def registration_handler():
    return SubnetRegistrationNotification()


@pytest.fixture
def coldkey_handler():
    return ColdkeySwapNotification()


@pytest.fixture
def dissolution_handler():
    return SubnetDissolutionNotification()


@pytest.fixture
def sudo_handler():
    return SudoNotification()


# ── AdminUtilsNotification ─────────────────────────────────────────────


def test_admin_format_shows_old_to_new(admin_handler):
    extrinsics = [
        {
            "call_module": "AdminUtils",
            "call_function": "sudo_set_tempo",
            "netuid": 1,
            "extrinsic_index": 5,
            "call_args": [{"name": "netuid", "value": 1}, {"name": "tempo", "value": 360}],
            "previous_values": {"tempo": 100},
        }
    ]
    payload = admin_handler.format_message(100, extrinsics)

    assert payload["flags"] == 1 << 2
    content = payload["content"]
    assert "**Block #100**" in content
    assert "**Subnet 1**" in content
    assert "**tempo**: `100` → `360`" in content
    assert "taostats.io" in content


def test_admin_format_groups_by_subnet(admin_handler):
    extrinsics = [
        {
            "call_module": "AdminUtils",
            "call_function": "sudo_set_tempo",
            "netuid": 1,
            "extrinsic_index": 0,
            "call_args": [{"name": "netuid", "value": 1}, {"name": "tempo", "value": 360}],
            "previous_values": {},
        },
        {
            "call_module": "AdminUtils",
            "call_function": "sudo_set_tempo",
            "netuid": 2,
            "extrinsic_index": 1,
            "call_args": [{"name": "netuid", "value": 2}, {"name": "tempo", "value": 720}],
            "previous_values": {},
        },
    ]
    content = admin_handler.format_message(100, extrinsics)["content"]

    assert "**Subnet 1**" in content
    assert "**Subnet 2**" in content


def test_admin_format_without_previous_values(admin_handler):
    extrinsics = [
        {
            "call_module": "AdminUtils",
            "call_function": "sudo_set_tempo",
            "netuid": 1,
            "extrinsic_index": 0,
            "call_args": [{"name": "netuid", "value": 1}, {"name": "tempo", "value": 360}],
        }
    ]
    content = admin_handler.format_message(100, extrinsics)["content"]
    assert "**tempo**: `N/A` → `360`" in content


# ── SubnetRegistrationNotification ─────────────────────────────────────


def test_registration_format_shows_details(registration_handler):
    extrinsics = [
        {
            "call_module": "SubtensorModule",
            "call_function": "register_network",
            "extrinsic_index": 3,
            "address": "5Gxyz...",
            "extrinsic_hash": "0xabc123",
            "call_args": [
                {"name": "hotkey", "value": "5Gkey..."},
            ],
        }
    ]
    content = registration_handler.format_message(200, extrinsics)["content"]

    assert "**Block #200**" in content
    assert "`register_network`" in content
    assert "**signer**: `5Gxyz...`" in content
    assert "**hotkey**: `5Gkey...`" in content
    assert "**hash**: `0xabc123`" in content


def test_registration_format_decodes_identity(registration_handler):
    extrinsics = [
        {
            "call_module": "SubtensorModule",
            "call_function": "register_network_with_identity",
            "extrinsic_index": 0,
            "address": "5Gxyz...",
            "extrinsic_hash": "0xabc",
            "call_args": [
                {
                    "name": "identity",
                    "value": {
                        "subnet_name": "0x" + "My Subnet".encode().hex(),
                        "github_repo": "0x" + "https://github.com/example".encode().hex(),
                    },
                },
            ],
        }
    ]
    content = registration_handler.format_message(300, extrinsics)["content"]

    assert "**subnet_name**: My Subnet" in content
    assert "**github_repo**: https://github.com/example" in content


# ── ColdkeySwapNotification ───────────────────────────────────────────


def test_coldkey_format_shows_params(coldkey_handler):
    extrinsics = [
        {
            "call_module": "SubtensorModule",
            "call_function": "schedule_coldkey_swap",
            "extrinsic_index": 4,
            "call_args": [
                {"name": "new_coldkey", "value": "5Gnew..."},
                {"name": "old_coldkey", "value": "5Gold..."},
            ],
        }
    ]
    content = coldkey_handler.format_message(400, extrinsics)["content"]

    assert "**Block #400**" in content
    assert "`schedule_coldkey_swap`" in content
    assert "**new_coldkey**: `5Gnew...`" in content
    assert "**old_coldkey**: `5Gold...`" in content


# ── SubnetDissolutionNotification ──────────────────────────────────────


def test_dissolution_sudo_wrapped_real_payload(dissolution_handler):
    """Sudo-wrapped dissolve_network from a real block routes and formats correctly."""
    extrinsics = [
        {
            "call_module": "Sudo",
            "call_function": "sudo",
            "extrinsic_index": 5,
            "netuid": None,
            "call_args": [
                {
                    "name": "call",
                    "type": "RuntimeCall",
                    "value": {
                        "call_index": "0x073d",
                        "call_function": "dissolve_network",
                        "call_module": "SubtensorModule",
                        "call_args": [
                            {
                                "name": "coldkey",
                                "type": "AccountId",
                                "value": "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
                            },
                            {"name": "netuid", "type": "NetUid", "value": 2},
                        ],
                    },
                }
            ],
            "success": True,
        }
    ]

    assert dissolution_handler.matches("SubtensorModule", "dissolve_network") is True

    content = dissolution_handler.format_message(9, extrinsics)["content"]
    assert "**Block #9**" in content
    assert "`dissolve_network`" in content
    assert "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY" in content


def test_dissolution_format_shows_function(dissolution_handler):
    extrinsics = [
        {
            "call_module": "SubtensorModule",
            "call_function": "dissolve_network",
            "extrinsic_index": 2,
            "netuid": 42,
            "call_args": [{"name": "netuid", "value": 42}],
        }
    ]
    content = dissolution_handler.format_message(500, extrinsics)["content"]

    assert "**Block #500**" in content
    assert "`dissolve_network`" in content


# ── SudoNotification ──────────────────────────────────────────────────


def test_sudo_format_generic(sudo_handler):
    extrinsics = [
        {
            "call_module": "Sudo",
            "call_function": "sudo",
            "extrinsic_index": 1,
            "netuid": None,
            "call_args": [{"name": "call", "value": "set_weights"}],
        }
    ]
    content = sudo_handler.format_message(600, extrinsics)["content"]

    assert "**Block #600**" in content
    assert "**Global**" in content


def test_sudo_format_groups_by_netuid(sudo_handler):
    extrinsics = [
        {
            "call_module": "Sudo",
            "call_function": "sudo",
            "extrinsic_index": 0,
            "netuid": 1,
            "call_args": [{"name": "call", "value": "foo"}],
        },
        {
            "call_module": "Sudo",
            "call_function": "sudo",
            "extrinsic_index": 1,
            "netuid": None,
            "call_args": [{"name": "call", "value": "bar"}],
        },
    ]
    content = sudo_handler.format_message(700, extrinsics)["content"]

    assert "**Subnet 1**" in content
    assert "**Global**" in content


# ── All handlers suppress embeds ──────────────────────────────────────


@pytest.mark.parametrize(
    "handler_fixture",
    ["admin_handler", "registration_handler", "coldkey_handler", "dissolution_handler", "sudo_handler"],
)
def test_all_handlers_suppress_embeds(handler_fixture, request):
    handler = request.getfixturevalue(handler_fixture)
    extrinsics = [
        {
            "call_module": "Test",
            "call_function": "test",
            "extrinsic_index": 0,
            "call_args": [],
            "netuid": 1,
            "address": "5Gxyz",
            "extrinsic_hash": "0xabc",
        }
    ]
    payload = handler.format_message(100, extrinsics)
    assert payload["flags"] == 1 << 2
