"""Test command to execute fast backfill synchronously with detailed timing logs."""

import time
from datetime import UTC, datetime
from decimal import Decimal

import bittensor as bt
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.metagraph.management.commands.fast_backfill import _get_metagraph_with_fallback
from apps.metagraph.models import (
    Block,
    Coldkey,
    Hotkey,
    MechanismMetrics,
    MetagraphDump,
    Neuron,
    NeuronSnapshot,
    Subnet,
)
from apps.metagraph.services.apy_sync_service import DumpMetadata
from apps.metagraph.utils import get_dumpable_blocks, get_epoch_containing_block

TAO_TO_RAO = 10**9


def _to_rao(tao_value: float | None) -> int:
    """Convert TAO value to rao (integer)."""
    if tao_value is None:
        return 0
    return int(Decimal(str(tao_value)) * TAO_TO_RAO)


def _get_epoch_position_str(block_number: int, netuid: int) -> str:
    """Determine the position of a block within its epoch."""
    epoch = get_epoch_containing_block(block_number, netuid)
    dumpable_blocks = get_dumpable_blocks(epoch)

    if block_number == dumpable_blocks[0]:
        return "start"
    if block_number == dumpable_blocks[-1]:
        return "end"
    return "inside"


class Command(BaseCommand):
    help = "Test fast backfill with detailed timing logs for each sync step."

    def handle(self, *args, **options) -> None:
        # Hardcoded test payload
        blocks = [
            (6116059, 1),
            (6116179, 1),
            (6116299, 1),
            (6116419, 1),
            (6116420, 1),
            (6116540, 1),
            (6116660, 1),
            (6116780, 1),
            (6116781, 1),
            (6116901, 1),
        ]
        network = "archive"
        lite = True

        self.stdout.write("Executing fast backfill with detailed logging...")
        self.stdout.write(f"Blocks: {len(blocks)}")
        self.stdout.write(f"Network: {network}")
        self.stdout.write(f"Lite: {lite}")
        self.stdout.write("")

        total_start = time.time()
        processed = 0
        errors = 0

        try:
            # Connect to bittensor network
            t0 = time.time()
            self.stdout.write(f"[CONNECT] Connecting to {network}...")
            subtensor = bt.Subtensor(network=network)
            self.stdout.write(f"[CONNECT] Connected in {time.time() - t0:.2f}s")
            self.stdout.write("")

            for block_num, netuid in blocks:
                try:
                    self.stdout.write(f"{'='*60}")
                    self.stdout.write(f"Processing block {block_num}, netuid {netuid}")
                    self.stdout.write(f"{'='*60}")

                    block_start = time.time()
                    started_at = datetime.now(UTC)

                    # Step 1: Fetch metagraph
                    t1 = time.time()
                    self.stdout.write(f"[FETCH] Fetching metagraph...")
                    metagraph = _get_metagraph_with_fallback(subtensor, netuid, block_num, lite=lite)
                    fetch_time = time.time() - t1
                    self.stdout.write(f"[FETCH] Done in {fetch_time:.2f}s")

                    finished_at = datetime.now(UTC)

                    if metagraph is None or len(metagraph.uids) == 0:
                        self.stderr.write(f"[ERROR] No metagraph data")
                        errors += 1
                        continue

                    n_neurons = int(metagraph.n.item()) if hasattr(metagraph.n, "item") else len(metagraph.uids)
                    self.stdout.write(f"[FETCH] Got {n_neurons} neurons")

                    # Step 2: Sync to database with detailed timing
                    stats = self._sync_with_logging(
                        metagraph=metagraph,
                        block_number=block_num,
                        dump_metadata=DumpMetadata(
                            netuid=netuid,
                            epoch_position=_get_epoch_position_str(block_num, netuid),
                            started_at=started_at,
                            finished_at=finished_at,
                        ),
                    )

                    processed += 1
                    total_block_time = time.time() - block_start
                    self.stdout.write(f"[TOTAL] Block completed in {total_block_time:.2f}s")
                    self.stdout.write(f"[STATS] neurons={stats['snapshots']}, dividends={stats['mechanism_metrics']}")
                    self.stdout.write("")

                except Exception as e:
                    errors += 1
                    self.stderr.write(self.style.ERROR(f"[ERROR] {e}"))
                    import traceback
                    traceback.print_exc()

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrupted by user"))

        total_time = time.time() - total_start
        avg_time = total_time / len(blocks) if blocks else 0

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("="*60))
        self.stdout.write(self.style.SUCCESS("SUMMARY"))
        self.stdout.write(self.style.SUCCESS("="*60))
        self.stdout.write(f"Processed: {processed}/{len(blocks)}")
        self.stdout.write(f"Errors: {errors}")
        self.stdout.write(f"Total time: {total_time:.2f}s")
        self.stdout.write(f"Avg time per block: {avg_time:.2f}s")

    def _sync_with_logging(self, metagraph, block_number: int, dump_metadata: DumpMetadata) -> dict[str, int]:
        """Sync metagraph with detailed timing for each step."""
        stats = {
            "coldkeys": 0,
            "hotkeys": 0,
            "neurons": 0,
            "snapshots": 0,
            "mechanism_metrics": 0,
        }

        # Caches
        coldkey_cache: dict[str, Coldkey] = {}
        hotkey_cache: dict[str, Hotkey] = {}
        neuron_cache: dict[tuple[int, int], Neuron] = {}
        hotkeys_to_update: set[int] = set()

        netuid = metagraph.netuid
        n_neurons = int(metagraph.n.item()) if hasattr(metagraph.n, "item") else len(metagraph.uids)

        # Timing accumulators
        timings = {
            "block_sync": 0.0,
            "subnet_sync": 0.0,
            "coldkey_sync": 0.0,
            "hotkey_sync": 0.0,
            "neuron_sync": 0.0,
            "snapshot_sync": 0.0,
            "metrics_sync": 0.0,
            "dump_sync": 0.0,
            "hotkey_update": 0.0,
            "data_extraction": 0.0,
        }

        with transaction.atomic():
            # Step 2a: Sync block
            t = time.time()
            self.stdout.write(f"[SYNC] Creating/updating block...")
            block, _ = Block.objects.get_or_create(
                number=block_number,
                defaults={
                    "timestamp": None,
                    "dump_started_at": dump_metadata.started_at,
                    "dump_finished_at": dump_metadata.finished_at,
                },
            )
            timings["block_sync"] = time.time() - t
            self.stdout.write(f"[SYNC] Block sync: {timings['block_sync']*1000:.1f}ms")

            # Step 2b: Sync subnet
            t = time.time()
            self.stdout.write(f"[SYNC] Creating/updating subnet...")
            subnet, _ = Subnet.objects.get_or_create(
                netuid=netuid,
                defaults={"name": f"Subnet {netuid}"},
            )
            timings["subnet_sync"] = time.time() - t
            self.stdout.write(f"[SYNC] Subnet sync: {timings['subnet_sync']*1000:.1f}ms")

            # Step 2c: Process validators only (skip miners)
            self.stdout.write(f"[SYNC] Processing {n_neurons} neurons (validators only)...")

            for i in range(n_neurons):
                # Extract data
                t = time.time()
                uid = int(metagraph.uids[i])
                hotkey_str = str(metagraph.hotkeys[i])
                coldkey_str = str(metagraph.coldkeys[i])
                stake = float(metagraph.stake[i])
                emission = float(metagraph.emission[i])
                is_validator = bool(metagraph.validator_permit[i]) if hasattr(metagraph, "validator_permit") else stake > 0
                timings["data_extraction"] += time.time() - t

                # Skip non-validators - we only need validator data for APY calculation
                if not is_validator:
                    continue

                t = time.time()
                trust = float(metagraph.trust[i]) if hasattr(metagraph, "trust") else 0.0
                rank = float(metagraph.ranks[i]) if hasattr(metagraph, "ranks") else 0.0
                is_active = bool(metagraph.active[i]) if hasattr(metagraph, "active") else True
                dividend = float(metagraph.dividends[i]) if hasattr(metagraph, "dividends") else 0.0
                incentive = float(metagraph.incentive[i]) if hasattr(metagraph, "incentive") else 0.0
                timings["data_extraction"] += time.time() - t

                # Sync coldkey
                t = time.time()
                if coldkey_str not in coldkey_cache:
                    coldkey, _ = Coldkey.objects.get_or_create(coldkey=coldkey_str)
                    coldkey_cache[coldkey_str] = coldkey
                timings["coldkey_sync"] += time.time() - t
                stats["coldkeys"] += 1

                # Sync hotkey
                t = time.time()
                if hotkey_str not in hotkey_cache:
                    coldkey = coldkey_cache[coldkey_str]
                    hotkey, created = Hotkey.objects.get_or_create(
                        hotkey=hotkey_str,
                        defaults={"coldkey": coldkey, "last_seen": timezone.now()},
                    )
                    if not created:
                        hotkeys_to_update.add(hotkey.id)
                    hotkey_cache[hotkey_str] = hotkey
                else:
                    hotkey = hotkey_cache[hotkey_str]
                    hotkeys_to_update.add(hotkey.id)
                timings["hotkey_sync"] += time.time() - t
                stats["hotkeys"] += 1

                # Sync neuron
                t = time.time()
                cache_key = (hotkey.id, subnet.netuid)
                if cache_key not in neuron_cache:
                    neuron, _ = Neuron.objects.get_or_create(
                        hotkey=hotkey,
                        subnet=subnet,
                        defaults={"uid": uid},
                    )
                    neuron_cache[cache_key] = neuron
                else:
                    neuron = neuron_cache[cache_key]
                timings["neuron_sync"] += time.time() - t
                stats["neurons"] += 1

                # Sync snapshot
                t = time.time()
                snapshot, _ = NeuronSnapshot.objects.update_or_create(
                    neuron=neuron,
                    block=block,
                    defaults={
                        "uid": uid,
                        "total_stake": _to_rao(stake),
                        "emissions": _to_rao(emission),
                        "is_validator": is_validator,
                        "trust": trust,
                        "rank": rank,
                        "is_active": is_active,
                        "axon_address": "",
                        "normalized_stake": 0.0,
                        "is_immune": False,
                        "has_any_weights": False,
                    },
                )
                timings["snapshot_sync"] += time.time() - t
                stats["snapshots"] += 1

                # Sync mechanism metrics
                t = time.time()
                if dividend > 0 or incentive > 0:
                    MechanismMetrics.objects.update_or_create(
                        snapshot=snapshot,
                        mech_id=0,
                        defaults={
                            "dividend": dividend,
                            "incentive": incentive,
                            "consensus": 0.0,
                            "validator_trust": 0.0,
                            "weights_sum": 0.0,
                        },
                    )
                    stats["mechanism_metrics"] += 1
                timings["metrics_sync"] += time.time() - t

            # Step 2d: Sync dump record
            t = time.time()
            self.stdout.write(f"[SYNC] Creating metagraph dump record...")
            epoch_position_map = {"start": 0, "inside": 1, "end": 2}
            MetagraphDump.objects.update_or_create(
                netuid=dump_metadata.netuid,
                block=block,
                defaults={
                    "epoch_position": epoch_position_map.get(dump_metadata.epoch_position),
                    "started_at": dump_metadata.started_at,
                    "finished_at": dump_metadata.finished_at,
                },
            )
            timings["dump_sync"] = time.time() - t
            self.stdout.write(f"[SYNC] Dump sync: {timings['dump_sync']*1000:.1f}ms")

            # Step 2e: Bulk update hotkey last_seen
            t = time.time()
            if hotkeys_to_update:
                self.stdout.write(f"[SYNC] Updating {len(hotkeys_to_update)} hotkey last_seen...")
                Hotkey.objects.filter(id__in=hotkeys_to_update).update(last_seen=timezone.now())
            timings["hotkey_update"] = time.time() - t
            self.stdout.write(f"[SYNC] Hotkey update: {timings['hotkey_update']*1000:.1f}ms")

        # Print timing summary
        n_validators = stats["snapshots"]
        self.stdout.write("")
        self.stdout.write(f"[TIMING] Validators synced: {n_validators}/{n_neurons} neurons")
        self.stdout.write(f"[TIMING] Data extraction:  {timings['data_extraction']*1000:.1f}ms total")
        self.stdout.write(f"[TIMING] Coldkey sync:     {timings['coldkey_sync']*1000:.1f}ms total")
        self.stdout.write(f"[TIMING] Hotkey sync:      {timings['hotkey_sync']*1000:.1f}ms total")
        self.stdout.write(f"[TIMING] Neuron sync:      {timings['neuron_sync']*1000:.1f}ms total")
        avg_snapshot_time = timings['snapshot_sync'] / n_validators * 1000 if n_validators > 0 else 0
        self.stdout.write(f"[TIMING] Snapshot sync:    {timings['snapshot_sync']*1000:.1f}ms total ({avg_snapshot_time:.2f}ms/validator)")
        self.stdout.write(f"[TIMING] Metrics sync:     {timings['metrics_sync']*1000:.1f}ms total")

        return stats
