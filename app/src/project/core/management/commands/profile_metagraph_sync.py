"""
Profile sync_metagraph_for_block to find where the 40+ seconds are spent.

Usage:
    uv run --directory app manage.py profile_metagraph_sync --block 7925512 --netuid 120
    uv run --directory app manage.py profile_metagraph_sync --block 7925512 --netuid 120 --skip-db
"""

import os
import time
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, reset_queries, transaction
from sentinel.v1.providers import pylon_provider
from sentinel.v1.services.sentinel import sentinel_service

import apps.metagraph.utils as metagraph_utils
from apps.metagraph.services.metagraph_service import MetagraphService
from apps.metagraph.services.metagraph_sync_service import DumpMetadata, MetagraphSyncService


class Timer:
    def __init__(self):
        self.elapsed_ms = 0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = round((time.perf_counter() - self._start) * 1000)


class Command(BaseCommand):
    help = "Profile sync_metagraph_for_block execution time by phase."

    def add_arguments(self, parser):
        parser.add_argument("--block", type=int, required=True, help="Block number")
        parser.add_argument("--netuid", type=int, required=True, help="Subnet netuid")
        parser.add_argument("--skip-db", action="store_true", help="Skip DB sync phase")
        parser.add_argument(
            "--count-queries", action="store_true", help="Count SQL queries per phase (enables DEBUG logging)"
        )

    def handle(self, *args, **options):
        block_number = options["block"]
        netuid = options["netuid"]
        skip_db = options["skip_db"]
        count_queries = options["count_queries"]

        if count_queries:
            settings.DEBUG = True
            reset_queries()

        self.stdout.write(f"Profiling sync_metagraph_for_block(block={block_number}, netuid={netuid})")
        self.stdout.write(f"  METAGRAPH_LITE={settings.METAGRAPH_LITE}")
        self.stdout.write(f"  PYLON_URL={os.environ.get('PYLON_URL', 'not set')}")
        self.stdout.write("")

        # --- Provider fetch phases ---
        with Timer() as t_provider:
            provider = pylon_provider()
        self._report("Create pylon_provider", t_provider)

        with Timer() as t_service:
            service = sentinel_service(provider)
        self._report("Create sentinel_service", t_service)

        with Timer() as t_ingest:
            subnet = service.ingest_subnet(netuid, block_number, lite=settings.METAGRAPH_LITE)
        self._report("ingest_subnet (provider fetch)", t_ingest)

        metagraph = subnet.metagraph
        if not metagraph:
            self.stdout.write(self.style.WARNING("\nNo metagraph data found."))
            return

        neuron_count = len(metagraph.neurons) if metagraph.neurons else 0
        weight_count = len(metagraph.weights) if metagraph.weights else 0
        bond_count = len(metagraph.bonds) if metagraph.bonds else 0
        mech_count = sum(len(n.mechanisms) for n in metagraph.neurons) if metagraph.neurons else 0
        self.stdout.write(
            f"\n  Metagraph: {neuron_count} neurons, {mech_count} mechanisms, {weight_count} weights, {bond_count} bonds"
        )

        # --- Serialization phases ---
        with Timer() as t_serialize:
            json_bytes = metagraph.model_dump_json().encode()
        self._report("model_dump_json (serialize)", t_serialize)
        self.stdout.write(f"    Artifact size: {len(json_bytes) / 1024 / 1024:.1f} MB")

        with Timer() as t_artifact:
            MetagraphService.store_metagraph_artifact(metagraph)
        self._report("store_metagraph_artifact (disk)", t_artifact)

        # --- DB sync phases (broken down) ---
        t_keys = Timer()
        t_neurons = Timer()
        t_snapshots = Timer()
        t_mechanisms = Timer()
        t_weights = Timer()
        t_bonds = Timer()
        t_collaterals = Timer()
        t_flush = Timer()
        t_block_sync = Timer()
        t_subnet_sync = Timer()
        t_dump_sync = Timer()

        if skip_db:
            self.stdout.write("\n  Skipping DB sync (--skip-db)")
        else:
            started_at = datetime.now(UTC)
            finished_at = datetime.now(UTC)

            epoch = metagraph_utils.get_epoch_containing_block(block_number, netuid)
            dumpable_blocks = metagraph_utils.get_dumpable_blocks(epoch)
            if block_number == dumpable_blocks[0]:
                epoch_position = "start"
            elif block_number == dumpable_blocks[-1]:
                epoch_position = "end"
            else:
                epoch_position = "inside"

            dump_metadata = DumpMetadata(
                netuid=netuid,
                epoch_position=epoch_position,
                started_at=started_at,
                finished_at=finished_at,
            )

            self.stdout.write("\n  --- DB sync breakdown ---")

            if count_queries:
                reset_queries()

            sync_service = MetagraphSyncService()

            with transaction.atomic():
                # Block
                with t_block_sync:
                    block_obj = sync_service._sync_block(metagraph.block, dump_metadata)
                self._report("Sync block", t_block_sync, count_queries)

                # Subnet
                with t_subnet_sync:
                    subnet_obj = sync_service._sync_subnet(metagraph.subnet)
                self._report("Sync subnet", t_subnet_sync, count_queries)

                # Keys (coldkeys, hotkeys, evmkeys)
                with t_keys:
                    for ns in metagraph.neurons:
                        nr = ns.neuron
                        if nr.hotkey:
                            if nr.hotkey.coldkey:
                                sync_service._key_cache.get_or_create_coldkey(nr.hotkey.coldkey.coldkey)
                            sync_service._key_cache.get_or_create_hotkey(
                                nr.hotkey.hotkey,
                                {"coldkey": nr.hotkey.coldkey.coldkey} if nr.hotkey.coldkey else None,
                            )
                        if nr.evm_key:
                            sync_service._key_cache.get_or_create_evmkey(nr.evm_key.evm_address)
                self._report(f"Sync keys ({neuron_count} neurons)", t_keys, count_queries)

                # Neurons
                with t_neurons:
                    for ns in metagraph.neurons:
                        sync_service._sync_neuron(ns.neuron, subnet_obj)
                self._report(f"Sync neurons ({neuron_count})", t_neurons, count_queries)

                # Snapshots
                with t_snapshots:
                    snapshot_map = {}
                    for ns in metagraph.neurons:
                        hotkey = sync_service._key_cache.get_cached_hotkey(ns.neuron.hotkey.hotkey)
                        neuron = sync_service._neuron_cache.get((hotkey.id, subnet_obj.netuid))
                        snapshot = sync_service._sync_neuron_snapshot(ns, neuron, block_obj)
                        snapshot_map[ns.neuron.hotkey.hotkey] = snapshot
                self._report(f"Sync snapshots ({neuron_count})", t_snapshots, count_queries)

                # Mechanism metrics
                with t_mechanisms:
                    for ns in metagraph.neurons:
                        snapshot = snapshot_map[ns.neuron.hotkey.hotkey]
                        for mech in ns.mechanisms:
                            sync_service._sync_mechanism_metrics(mech, snapshot)
                self._report(f"Sync mechanisms ({mech_count})", t_mechanisms, count_queries)

                # Weights
                with t_weights:
                    if metagraph.weights:
                        sync_service._relation_syncer.sync_weights(metagraph.weights, block_obj, subnet_obj)
                self._report(f"Sync weights ({weight_count})", t_weights, count_queries)

                # Bonds
                with t_bonds:
                    if metagraph.bonds:
                        sync_service._relation_syncer.sync_bonds(metagraph.bonds, block_obj, subnet_obj)
                self._report(f"Sync bonds ({bond_count})", t_bonds, count_queries)

                # Collaterals
                with t_collaterals:
                    if metagraph.collaterals:
                        sync_service._relation_syncer.sync_collaterals(metagraph.collaterals, block_obj, subnet_obj)
                self._report("Sync collaterals", t_collaterals, count_queries)

                # Dump record
                with t_dump_sync:
                    sync_service._sync_metagraph_dump(dump_metadata, block_obj, subnet_obj)
                self._report("Sync dump record", t_dump_sync, count_queries)

                # Flush hotkey last_seen
                with t_flush:
                    sync_service._key_cache.flush_hotkey_last_seen()
                self._report("Flush hotkey last_seen", t_flush, count_queries)

        # --- Summary ---
        self.stdout.write("\n--- Summary ---")
        rows = [
            ("Provider create", t_provider),
            ("Service create", t_service),
            ("Ingest (fetch)", t_ingest),
            ("Serialize JSON", t_serialize),
            ("Store artifact", t_artifact),
        ]
        if not skip_db:
            rows.extend(
                [
                    ("  Block", t_block_sync),
                    ("  Subnet", t_subnet_sync),
                    ("  Keys", t_keys),
                    ("  Neurons", t_neurons),
                    ("  Snapshots", t_snapshots),
                    ("  Mechanisms", t_mechanisms),
                    ("  Weights", t_weights),
                    ("  Bonds", t_bonds),
                    ("  Collaterals", t_collaterals),
                    ("  Dump record", t_dump_sync),
                    ("  Flush last_seen", t_flush),
                ]
            )

        total = sum(t.elapsed_ms for _, t in rows)
        for label, t in rows:
            self.stdout.write(f"  {label + ':':<22} {t.elapsed_ms:>6}ms")
        self.stdout.write(f"  {'─' * 28}")
        self.stdout.write(f"  {'Total:':<22} {total:>6}ms")

        if count_queries:
            self.stdout.write(f"\n  Total SQL queries: {len(connection.queries)}")

    def _report(self, label, timer, count_queries=False):
        extra = ""
        if count_queries:
            q = len(connection.queries)
            extra = f" ({q} queries total)"
        self.stdout.write(f"  {label}: {timer.elapsed_ms}ms{extra}")
