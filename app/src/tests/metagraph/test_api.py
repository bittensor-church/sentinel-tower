"""Metagraph export API: ``GET /api/v1/metagraph-data/``.

Epoch layout used below, for netuid 1 (an epoch starts where (block + netuid + 2) % 361 == 0):

    epoch A: blocks 358..718, dumped at 358, 478, 598, 718
    epoch B: blocks 719..1079, dumped at 719, 839, 959, 1079
"""

from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone

from tests.factories.metagraph import (
    BlockFactory,
    ColdkeyFactory,
    HotkeyFactory,
    MetagraphDumpFactory,
    NeuronFactory,
    NeuronSnapshotFactory,
    SubnetFactory,
    WeightFactory,
)

URL = "/api/v1/metagraph-data/"
BEARER = "test-token"
NETUID = 1
RAO = 10**9

EPOCH_A_END = 718
EPOCH_B_MID = 839
EPOCH_B_END = 1079

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def api_tokens(settings):
    settings.METAGRAPH_API_TOKENS = [BEARER, "second-consumer-token"]
    settings.METAGRAPH_API_MAX_BLOCKS = 50_400


@pytest.fixture
def subnet():
    return SubnetFactory(netuid=NETUID)


@pytest.fixture
def neurons(subnet):
    """One validator (uid 0, labelled) and two miners (uid 1 and 3; uid 2 is an empty slot)."""
    return {
        "validator": NeuronFactory(
            hotkey=HotkeyFactory(hotkey="hk-validator", label="Validator One"), subnet=subnet, uid=0
        ),
        "miner_1": NeuronFactory(hotkey=HotkeyFactory(hotkey="hk-miner-1"), subnet=subnet, uid=1),
        "miner_3": NeuronFactory(hotkey=HotkeyFactory(hotkey="hk-miner-3"), subnet=subnet, uid=3),
    }


def _dump(neurons, number, *, weights=None, finished=True, pruned=False, timestamp=None):
    """Store a metagraph dump at `number`: a snapshot of every neuron plus the validator's weights."""
    block = BlockFactory(
        number=number, timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=12 * number)
    )
    MetagraphDumpFactory(
        netuid=NETUID,
        block=block,
        finished_at=timezone.now() if finished else None,
        retention_pruned_at=timezone.now() if pruned else None,
    )
    NeuronSnapshotFactory(
        neuron=neurons["validator"], block=block, total_stake=2500 * RAO, is_validator=True, is_active=True
    )
    NeuronSnapshotFactory(neuron=neurons["miner_1"], block=block, total_stake=3 * RAO // 2, is_active=True)
    NeuronSnapshotFactory(neuron=neurons["miner_3"], block=block, total_stake=0, is_active=False)
    for target, weight in (weights if weights is not None else {"miner_1": 0.25, "miner_3": 0.75}).items():
        WeightFactory(
            source_neuron=neurons["validator"], target_neuron=neurons[target], block=block, mech_id=0, weight=weight
        )
    return block


def _get(client, token=BEARER, **params):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return client.get(URL, params, headers=headers)


# --- authentication -----------------------------------------------------------------------


def test__endpoint_does_not_exist_while_no_token_is_configured(client, settings, neurons):
    settings.METAGRAPH_API_TOKENS = []
    _dump(neurons, EPOCH_A_END)

    response = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 404


@pytest.mark.parametrize("token", [None, "", "wrong-token", "test-toke", "test-token-and-more"])
def test__request_without_a_valid_token_is_rejected(client, neurons, token):
    _dump(neurons, EPOCH_A_END)

    response = _get(client, token=token, netuid=NETUID, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == "Bearer"
    assert response.json() == {"error": "Missing or invalid bearer token."}


def test__token_must_use_the_bearer_scheme(client, neurons):
    _dump(neurons, EPOCH_A_END)

    response = client.get(
        URL,
        {"netuid": NETUID, "start_block": 358, "end_block": EPOCH_A_END},
        headers={"Authorization": f"Token {BEARER}"},
    )

    assert response.status_code == 401


def test__every_configured_token_is_accepted(client, neurons):
    _dump(neurons, EPOCH_A_END)

    response = _get(client, token="second-consumer-token", netuid=NETUID, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 200


def test__only_get_is_allowed(client):
    response = client.post(URL, headers={"Authorization": f"Bearer {BEARER}"})

    assert response.status_code == 405


# --- data ---------------------------------------------------------------------------------


def test__returns_one_snapshot_per_epoch_with_hotkeys_stakes_weights_and_labels(client, neurons):
    _dump(neurons, 598)  # earlier dump of epoch A: superseded by the one at 718
    _dump(neurons, EPOCH_A_END, weights={"miner_1": 0.25, "miner_3": 0.75})
    _dump(neurons, EPOCH_B_MID, weights={"miner_1": 1.0})  # the latest dump of epoch B in the range

    response = _get(client, netuid=NETUID, start_block=358, end_block=900)

    assert response.status_code == 200
    assert response.json() == {
        "netuid": NETUID,
        "mech_id": 0,
        "start_block": 358,
        "end_block": 900,
        "blocks": [EPOCH_A_END, EPOCH_B_MID],
        "skipped_blocks": [],
        "hotkeys": {
            "718": [
                ["hk-validator", True, True],
                ["hk-miner-1", False, True],
                [None, False, False],
                ["hk-miner-3", False, False],
            ],
            "839": [
                ["hk-validator", True, True],
                ["hk-miner-1", False, True],
                [None, False, False],
                ["hk-miner-3", False, False],
            ],
        },
        # stake is stored in rao and returned in TAO
        "stakes": {
            "718": {"0": 2500.0, "1": 1.5, "3": 0.0},
            "839": {"0": 2500.0, "1": 1.5, "3": 0.0},
        },
        "weights": {
            "718": {"0": {"1": 0.25, "3": 0.75}},
            "839": {"0": {"1": 1.0}},
        },
        "labels": {"hk-validator": "Validator One"},
    }


def test__date_range_is_resolved_through_block_timestamps(client, neurons):
    base = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    _dump(neurons, 598, timestamp=base)
    _dump(neurons, EPOCH_A_END, timestamp=base + timedelta(minutes=24))
    _dump(neurons, EPOCH_B_END, timestamp=base + timedelta(minutes=96))

    response = _get(
        client,
        netuid=NETUID,
        # no offset: taken as UTC. Starts after block 598, ends before block 1079.
        start_date="2026-03-01T12:10:00",
        end_date="2026-03-01T13:00:00+00:00",
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["start_block"], body["end_block"]) == (EPOCH_A_END, EPOCH_A_END)
    assert body["blocks"] == [EPOCH_A_END]


def test__other_subnets_and_other_mechanisms_are_left_out(client, neurons):
    block = _dump(neurons, EPOCH_A_END)
    # the same block, another subnet
    other_subnet = SubnetFactory(netuid=7)
    foreign = NeuronFactory(hotkey=HotkeyFactory(hotkey="hk-foreign", label="Foreign"), subnet=other_subnet, uid=9)
    NeuronSnapshotFactory(neuron=foreign, block=block, total_stake=RAO, is_validator=True, is_active=True)
    MetagraphDumpFactory(netuid=7, block=block, finished_at=timezone.now())
    # the same validator, another mechanism
    WeightFactory(
        source_neuron=neurons["validator"], target_neuron=neurons["miner_1"], block=block, mech_id=1, weight=0.9
    )

    body = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END).json()

    assert len(body["hotkeys"]["718"]) == 4
    assert body["labels"] == {"hk-validator": "Validator One"}
    assert body["weights"] == {"718": {"0": {"1": 0.25, "3": 0.75}}}

    mech_1 = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END, mech_id=1).json()
    assert mech_1["weights"] == {"718": {"0": {"1": 0.9}}}


def test__label_falls_back_from_hotkey_to_coldkey_label_to_onchain_identity(client, subnet):
    def neuron(uid, hotkey, *, hotkey_label="", coldkey_label="", identity_name=None):
        coldkey = ColdkeyFactory(coldkey=f"ck-{uid}", label=coldkey_label, identity_name=identity_name)
        return NeuronFactory(
            hotkey=HotkeyFactory(hotkey=hotkey, label=hotkey_label, coldkey=coldkey), subnet=subnet, uid=uid
        )

    named = {
        "validator": neuron(
            0, "hk-all", hotkey_label="Hotkey label", coldkey_label="Coldkey label", identity_name="Identity"
        ),
        "miner_1": neuron(1, "hk-coldkey", coldkey_label="Coldkey label", identity_name="Identity"),
        "miner_3": neuron(3, "hk-identity", identity_name="Identity"),
    }
    unnamed = neuron(4, "hk-unnamed")
    block = _dump(named, EPOCH_A_END)
    NeuronSnapshotFactory(neuron=unnamed, block=block)

    body = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END).json()

    assert body["labels"] == {"hk-all": "Hotkey label", "hk-coldkey": "Coldkey label", "hk-identity": "Identity"}


def test__unfinished_and_pruned_dumps_are_ignored(client, neurons):
    _dump(neurons, 598)
    _dump(neurons, EPOCH_A_END, finished=False)
    _dump(neurons, EPOCH_B_MID, pruned=True)

    body = _get(client, netuid=NETUID, start_block=358, end_block=900).json()

    # epoch A falls back to its earlier finished dump; epoch B has nothing usable
    assert body["blocks"] == [598]


def test__snapshots_without_weights_are_reported_as_skipped(client, neurons):
    _dump(neurons, EPOCH_A_END, weights={})  # e.g. weights already removed by retention
    _dump(neurons, EPOCH_B_END)

    body = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_B_END).json()

    assert body["blocks"] == [EPOCH_B_END]
    assert body["skipped_blocks"] == [EPOCH_A_END]
    assert list(body["hotkeys"]) == [str(EPOCH_B_END)]


# --- nothing to return --------------------------------------------------------------------


def test__range_with_snapshots_but_no_weights_at_all_is_a_404(client, neurons):
    _dump(neurons, EPOCH_A_END, weights={})

    response = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 404
    assert "no weights are stored" in response.json()["error"]


def test__range_without_snapshots_is_a_404(client, neurons):
    _dump(neurons, EPOCH_B_END)

    response = _get(client, netuid=NETUID, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 404
    assert response.json() == {"error": "No metagraph snapshot is stored for this subnet in the requested range."}


def test__unknown_subnet_is_a_404(client, neurons):
    _dump(neurons, EPOCH_A_END)

    response = _get(client, netuid=99, start_block=358, end_block=EPOCH_A_END)

    assert response.status_code == 404
    assert response.json() == {"error": "Subnet 99 is not known."}


def test__date_before_any_recorded_block_is_a_404(client, neurons):
    _dump(neurons, EPOCH_A_END)

    response = _get(client, netuid=NETUID, start_date="2020-01-01", end_date="2020-01-02")

    assert response.status_code == 404
    assert response.json() == {"error": "No block is recorded at or before 'end_date'."}


# --- invalid requests ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "error"),
    [
        ({"start_block": 358, "end_block": 718}, "'netuid' is required."),
        ({"netuid": "abc", "start_block": 358, "end_block": 718}, "'netuid' must be an integer."),
        ({"netuid": -1, "start_block": 358, "end_block": 718}, "'netuid' must not be negative."),
        ({"netuid": NETUID, "end_block": 718}, "Either 'start_block' or 'start_date' is required."),
        ({"netuid": NETUID, "start_block": 358}, "Either 'end_block' or 'end_date' is required."),
        ({"netuid": NETUID, "start_block": 718, "end_block": 358}, "The end of the range is before its start."),
        ({"netuid": NETUID, "start_block": 0, "end_block": 50_401}, "The range may span at most 50400 blocks."),
        (
            {"netuid": NETUID, "start_date": "yesterday", "end_block": 718},
            "'start_date' must be an ISO 8601 date or datetime.",
        ),
        ({"netuid": NETUID, "start_block": 358, "end_block": 718, "mech_id": "x"}, "'mech_id' must be an integer."),
    ],
)
def test__invalid_parameters_are_a_400_with_the_reason(client, neurons, params, error):
    _dump(neurons, EPOCH_A_END)

    response = _get(client, **params)

    assert response.status_code == 400
    assert response.json() == {"error": error}
