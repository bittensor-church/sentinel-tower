"""
Read-only HTTP API that exports metagraph history to other services.

``GET /api/v1/metagraph-data/`` returns, for one subnet and a block or time span, one
snapshot per epoch: every neuron's hotkey, validator/active flags and stake, the weights
recorded at that block, and the names of known hotkeys.

Requests carry ``Authorization: Bearer <token>`` with one of ``METAGRAPH_API_TOKENS``.
While no token is configured the endpoint answers 404.
"""

import hmac
from datetime import UTC, datetime
from typing import Any

import structlog
from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from . import utils as metagraph_utils
from .models import Block, MetagraphDump, NeuronSnapshot, Subnet, Weight

logger = structlog.get_logger()

RAO_PER_TAO = 10**9

# [hotkey, is_validator, is_active]; hotkey is None for a slot with no neuron.
HotkeySlot = tuple[str | None, bool, bool]
EMPTY_SLOT: HotkeySlot = (None, False, False)


class InvalidRequest(Exception):
    """A request parameter is missing, malformed or out of range."""


class NoData(Exception):
    """The request is valid, but nothing is stored for it."""


def _is_authorized(request: HttpRequest) -> bool:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return False
    # compare against every token, without short-circuiting on the first match
    matches = [hmac.compare_digest(token.encode(), valid.encode()) for valid in settings.METAGRAPH_API_TOKENS]
    return any(matches)


def _int_param(request: HttpRequest, name: str, default: int | None = None) -> int:
    raw = request.GET.get(name)
    if raw is None or raw == "":
        if default is None:
            raise InvalidRequest(f"'{name}' is required.")
        return default
    try:
        value = int(raw)
    except ValueError:
        raise InvalidRequest(f"'{name}' must be an integer.") from None
    if value < 0:
        raise InvalidRequest(f"'{name}' must not be negative.")
    return value


def _datetime_param(request: HttpRequest, name: str) -> datetime | None:
    raw = request.GET.get(name)
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise InvalidRequest(f"'{name}' must be an ISO 8601 date or datetime.") from None
    # a value without an offset is taken as UTC
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _resolve_block_range(request: HttpRequest) -> tuple[int, int]:
    """Turn ``start_block``/``start_date`` and ``end_block``/``end_date`` into block numbers."""
    start_date = _datetime_param(request, "start_date")
    end_date = _datetime_param(request, "end_date")

    if start_date is not None:
        start_block = (
            Block.objects.filter(timestamp__gte=start_date)
            .order_by("timestamp")
            .values_list("number", flat=True)
            .first()
        )
        if start_block is None:
            raise NoData("No block is recorded at or after 'start_date'.")
    elif request.GET.get("start_block"):
        start_block = _int_param(request, "start_block")
    else:
        raise InvalidRequest("Either 'start_block' or 'start_date' is required.")

    if end_date is not None:
        end_block = (
            Block.objects.filter(timestamp__lte=end_date)
            .order_by("-timestamp")
            .values_list("number", flat=True)
            .first()
        )
        if end_block is None:
            raise NoData("No block is recorded at or before 'end_date'.")
    elif request.GET.get("end_block"):
        end_block = _int_param(request, "end_block")
    else:
        raise InvalidRequest("Either 'end_block' or 'end_date' is required.")

    if end_block < start_block:
        raise InvalidRequest("The end of the range is before its start.")
    if end_block - start_block > settings.METAGRAPH_API_MAX_BLOCKS:
        raise InvalidRequest(f"The range may span at most {settings.METAGRAPH_API_MAX_BLOCKS} blocks.")
    return start_block, end_block


def _epoch_snapshot_blocks(netuid: int, start_block: int, end_block: int) -> list[int]:
    """
    Pick one block per epoch: the latest one in the range with a finished dump whose
    snapshots retention has not removed.
    """
    dumped_blocks = MetagraphDump.objects.filter(
        netuid=netuid,
        block_id__gte=start_block,
        block_id__lte=end_block,
        finished_at__isnull=False,
        retention_pruned_at__isnull=True,
    ).values_list("block_id", flat=True)

    latest_by_epoch: dict[int, int] = {}
    for block in dumped_blocks:
        epoch_start = metagraph_utils.get_epoch_containing_block(block, netuid).start
        latest_by_epoch[epoch_start] = max(block, latest_by_epoch.get(epoch_start, block))
    return sorted(latest_by_epoch.values())


def _collect_metagraph_data(netuid: int, mech_id: int, start_block: int, end_block: int) -> dict[str, Any]:
    if not Subnet.objects.filter(netuid=netuid).exists():
        raise NoData(f"Subnet {netuid} is not known.")

    epoch_blocks = _epoch_snapshot_blocks(netuid, start_block, end_block)
    if not epoch_blocks:
        raise NoData("No metagraph snapshot is stored for this subnet in the requested range.")

    weight_rows = list(
        Weight.objects.filter(
            block_id__in=epoch_blocks,
            mech_id=mech_id,
            source_neuron__subnet_id=netuid,
            target_neuron__subnet_id=netuid,
        ).values_list("block_id", "source_neuron_id", "target_neuron_id", "weight")
    )
    # Weights have a shorter retention than snapshots and are not stored at all in lite
    # mode. A snapshot without them cannot be used for consensus calculations, so such
    # blocks are reported separately instead of being returned with an empty matrix.
    blocks_with_weights = {row[0] for row in weight_rows}
    blocks = [block for block in epoch_blocks if block in blocks_with_weights]
    skipped_blocks = [block for block in epoch_blocks if block not in blocks_with_weights]
    if not blocks:
        raise NoData(
            "Snapshots exist for the requested range, but no weights are stored for them "
            "(outside the weight retention window, or weights are not collected)."
        )

    snapshots = list(
        NeuronSnapshot.objects.filter(block_id__in=blocks, neuron__subnet_id=netuid).values_list(
            "block_id",
            "neuron_id",
            "uid",
            "total_stake",
            "is_validator",
            "is_active",
            "neuron__hotkey__hotkey",
            "neuron__hotkey__label",
            "neuron__hotkey__coldkey__label",
            "neuron__hotkey__coldkey__identity_name",
        )
    )
    if not snapshots:
        raise NoData("No neuron snapshots are stored for the requested range.")

    slot_count = max(uid for _block, _neuron, uid, *_rest in snapshots) + 1
    hotkeys: dict[int, list[HotkeySlot]] = {block: [EMPTY_SLOT] * slot_count for block in blocks}
    stakes: dict[int, dict[int, float]] = {block: {} for block in blocks}
    labels: dict[str, str] = {}
    uid_by_neuron: dict[tuple[int, int], int] = {}

    for (
        block,
        neuron_id,
        uid,
        total_stake,
        is_validator,
        is_active,
        hotkey,
        hotkey_label,
        coldkey_label,
        identity_name,
    ) in snapshots:
        hotkeys[block][uid] = (hotkey, is_validator, is_active)
        stakes[block][uid] = float(total_stake) / RAO_PER_TAO
        uid_by_neuron[(block, neuron_id)] = uid
        # the same precedence as the dashboards: manual labels first, then the on-chain identity
        label = hotkey_label or coldkey_label or identity_name
        if label:
            labels[hotkey] = label

    weights: dict[int, dict[int, dict[int, float]]] = {block: {} for block in blocks}
    for block, source_neuron_id, target_neuron_id, weight in weight_rows:
        source_uid = uid_by_neuron.get((block, source_neuron_id))
        target_uid = uid_by_neuron.get((block, target_neuron_id))
        if source_uid is None or target_uid is None:
            continue  # a weight row without a snapshot of both ends at this block
        weights[block].setdefault(source_uid, {})[target_uid] = weight

    return {
        "netuid": netuid,
        "mech_id": mech_id,
        "start_block": start_block,
        "end_block": end_block,
        "blocks": blocks,
        "skipped_blocks": skipped_blocks,
        "hotkeys": hotkeys,
        "stakes": stakes,
        "weights": weights,
        "labels": labels,
    }


@require_GET
def metagraph_data_view(request: HttpRequest) -> JsonResponse:
    """
    Query parameters:
        netuid       required
        start_block  or start_date (ISO 8601; UTC when it has no offset)
        end_block    or end_date
        mech_id      default 0

    Response keys:
        blocks          snapshot block numbers, one per epoch, ascending
        skipped_blocks  epoch snapshots left out because no weights are stored for them
        hotkeys         block -> list indexed by uid of [hotkey, is_validator, is_active]
        stakes          block -> uid -> total stake in TAO
        weights         block -> validator uid -> target uid -> weight
        labels          hotkey -> name, for hotkeys that have one: the hotkey's label, else its
                        coldkey's label, else the coldkey's on-chain identity
    """
    if not settings.METAGRAPH_API_TOKENS:
        return JsonResponse({"error": "Not found."}, status=404)
    if not _is_authorized(request):
        response = JsonResponse({"error": "Missing or invalid bearer token."}, status=401)
        response["WWW-Authenticate"] = "Bearer"
        return response

    try:
        netuid = _int_param(request, "netuid")
        mech_id = _int_param(request, "mech_id", default=0)
        start_block, end_block = _resolve_block_range(request)
        data = _collect_metagraph_data(netuid, mech_id, start_block, end_block)
    except InvalidRequest as e:
        return JsonResponse({"error": str(e)}, status=400)
    except NoData as e:
        return JsonResponse({"error": str(e)}, status=404)

    logger.info(
        "Served metagraph data",
        netuid=netuid,
        mech_id=mech_id,
        start_block=start_block,
        end_block=end_block,
        blocks=len(data["blocks"]),
        skipped_blocks=len(data["skipped_blocks"]),
    )
    return JsonResponse(data)
