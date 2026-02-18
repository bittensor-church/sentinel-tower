from typing import Any, ClassVar

import pytest

from apps.notifications.base import ExtrinsicNotification
from apps.notifications.channels import NotificationChannel


class FakeChannel(NotificationChannel):
    """Channel that records payloads instead of sending them."""

    def __init__(self, *, succeed=True):
        self.payloads: list[dict] = []
        self.should_succeed = succeed

    def send(self, payload: dict) -> bool:
        self.payloads.append(payload)
        return self.should_succeed


class StubNotification(ExtrinsicNotification):
    """Minimal concrete notification for testing base class behavior."""

    extrinsics: ClassVar[list[str]] = ["TestModule:test_function"]
    channels: ClassVar = []

    def format_message(self, block_number: int, extrinsics: list[dict[str, Any]]) -> dict[str, Any]:
        return {"content": f"Block {block_number}, {len(extrinsics)} extrinsics"}


# ── matches() ──────────────────────────────────────────────────────────


def test_matches_exact_module_function():
    n = StubNotification()
    assert n.matches("TestModule", "test_function") is True


def test_matches_wrong_function():
    n = StubNotification()
    assert n.matches("TestModule", "other_function") is False


def test_matches_wrong_module():
    n = StubNotification()
    assert n.matches("OtherModule", "test_function") is False


def test_matches_module_only_pattern():
    n = StubNotification()
    n.extrinsics = ["AdminUtils"]
    assert n.matches("AdminUtils", "sudo_set_tempo") is True
    assert n.matches("AdminUtils", "any_function") is True
    assert n.matches("OtherModule", "sudo_set_tempo") is False


def test_matches_multiple_patterns():
    n = StubNotification()
    n.extrinsics = ["SubtensorModule:register_network", "SubtensorModule:register_network_with_identity"]
    assert n.matches("SubtensorModule", "register_network") is True
    assert n.matches("SubtensorModule", "register_network_with_identity") is True
    assert n.matches("SubtensorModule", "dissolve_network") is False


# ── notify() ───────────────────────────────────────────────────────────


def test_notify_filters_failed_when_success_only():
    channel = FakeChannel()
    n = StubNotification()
    n.channels = [channel]

    extrinsics = [
        {"success": True, "call_module": "TestModule"},
        {"success": False, "call_module": "TestModule"},
    ]
    count = n.notify(100, extrinsics)

    assert count == 1
    assert "1 extrinsics" in channel.payloads[0]["content"]


def test_notify_returns_zero_when_all_failed():
    channel = FakeChannel()
    n = StubNotification()
    n.channels = [channel]

    assert n.notify(100, [{"success": False}]) == 0
    assert channel.payloads == []


def test_notify_skips_success_filter_when_disabled():
    channel = FakeChannel()
    n = StubNotification()
    n.channels = [channel]
    n.success_only = False

    assert n.notify(100, [{"success": False}]) == 1


def test_notify_returns_zero_when_channel_fails():
    channel = FakeChannel(succeed=False)
    n = StubNotification()
    n.channels = [channel]

    assert n.notify(100, [{"success": True}]) == 0


def test_notify_sends_to_multiple_channels():
    ch1, ch2 = FakeChannel(), FakeChannel()
    n = StubNotification()
    n.channels = [ch1, ch2]

    count = n.notify(100, [{"success": True}])
    assert count == 1
    assert len(ch1.payloads) == 1
    assert len(ch2.payloads) == 1


def test_notify_empty_extrinsics():
    n = StubNotification()
    n.channels = [FakeChannel()]
    assert n.notify(100, []) == 0


# ── unwrap_sudo_call() ────────────────────────────────────────────────


def test_unwrap_non_sudo_returned_as_is():
    ext = {"call_module": "AdminUtils", "call_function": "sudo_set_tempo"}
    assert ExtrinsicNotification.unwrap_sudo_call(ext) is ext


def test_unwrap_extracts_inner_call():
    ext = {
        "call_module": "Sudo",
        "call_function": "sudo",
        "netuid": None,
        "call_args": [
            {
                "name": "call",
                "value": {
                    "call_module": "AdminUtils",
                    "call_function": "sudo_set_tempo",
                    "call_args": [
                        {"name": "netuid", "value": 1},
                        {"name": "tempo", "value": 360},
                    ],
                },
            }
        ],
    }
    result = ExtrinsicNotification.unwrap_sudo_call(ext)

    assert result["call_module"] == "AdminUtils"
    assert result["call_function"] == "sudo_set_tempo"
    assert result["netuid"] == 1
    assert result["_is_sudo"] is True
    assert len(result["call_args"]) == 2


def test_unwrap_preserves_outer_netuid():
    ext = {
        "call_module": "Sudo",
        "call_function": "sudo",
        "netuid": 5,
        "call_args": [
            {
                "name": "call",
                "value": {
                    "call_module": "AdminUtils",
                    "call_function": "sudo_set_tempo",
                    "call_args": [{"name": "netuid", "value": 1}],
                },
            }
        ],
    }
    result = ExtrinsicNotification.unwrap_sudo_call(ext)
    assert result["netuid"] == 5


def test_unwrap_sudo_without_dict_value():
    ext = {
        "call_module": "Sudo",
        "call_function": "sudo",
        "call_args": [{"name": "call", "value": "not_a_dict"}],
    }
    result = ExtrinsicNotification.unwrap_sudo_call(ext)
    assert result["call_module"] == "Sudo"


# ── format_value() ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "N/A"),
        ([1, 2, 3, 4], "[4 items]"),
        ([1, 2], "[1, 2]"),
        ("hello", "hello"),
        (42, "42"),
    ],
)
def test_format_value(value, expected):
    assert ExtrinsicNotification.format_value(value) == expected


# ── format_call_args() ────────────────────────────────────────────────


def test_format_call_args_none():
    assert ExtrinsicNotification.format_call_args(None) == "None"


def test_format_call_args_empty():
    assert ExtrinsicNotification.format_call_args([]) == "None"


def test_format_call_args_simple():
    result = ExtrinsicNotification.format_call_args([{"name": "tempo", "value": 360}])
    assert "**tempo**: `360`" in result


def test_format_call_args_truncates_long_string():
    result = ExtrinsicNotification.format_call_args([{"name": "key", "value": "a" * 30}])
    assert "..." in result


def test_format_call_args_dict_abbreviated():
    result = ExtrinsicNotification.format_call_args([{"name": "identity", "value": {"name": "test"}}])
    assert "{...}" in result


def test_format_call_args_long_list_abbreviated():
    result = ExtrinsicNotification.format_call_args([{"name": "data", "value": [1, 2, 3, 4]}])
    assert "[4 items]" in result


# ── decode_hex_field() ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0x68656c6c6f", "hello"),
        ("68656c6c6f", "hello"),
        (42, "42"),
        (None, ""),
        ("not_hex_at_all", "not_hex_at_all"),
    ],
)
def test_decode_hex_field(value, expected):
    assert ExtrinsicNotification.decode_hex_field(value) == expected


# ── taostats_link() ───────────────────────────────────────────────────


def test_taostats_link():
    assert ExtrinsicNotification.taostats_link(123456, 7) == "https://taostats.io/extrinsic/123456-0007?network=finney"


def test_taostats_link_zero_index():
    assert ExtrinsicNotification.taostats_link(100, 0) == "https://taostats.io/extrinsic/100-0000?network=finney"


# ── group_by_netuid() ─────────────────────────────────────────────────


def test_group_by_netuid():
    extrinsics = [
        {"netuid": 1, "id": "a"},
        {"netuid": 2, "id": "b"},
        {"netuid": 1, "id": "c"},
        {"id": "d"},
    ]
    groups = ExtrinsicNotification.group_by_netuid(extrinsics)
    assert len(groups[1]) == 2
    assert len(groups[2]) == 1
    assert len(groups[None]) == 1
