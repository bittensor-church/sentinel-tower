"""Collect historical APY epoch data from a subtensor archive node.

Handles two eras automatically:
- Modern era (runtime v223+): uses getSelectiveMetagraph for exact alpha dividends
- Legacy era (older blocks): falls back to getNeuronsLite with approximate alpha_earned

Usage:
    # Dry run to see plan
    python manage.py collect_apy --start-block 3200000 --end-block 5200000 --dry-run

    # Quick timing experiment (10 epochs per subnet)
    python manage.py collect_apy --start-block 5000000 --end-block 7000000 --limit-epochs 10

    # Full collection spanning both eras
    python manage.py collect_apy --start-block 3200000 --end-block 7000000 --subnets 1 2 3
"""

import csv
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import bittensor as bt
import structlog
from bittensor.core.chain_data.metagraph_info import SelectiveMetagraphIndex
from django.core.management.base import BaseCommand

from apps.metagraph.services.metagraph_service import MetagraphService

logger = structlog.get_logger()

# Selective metagraph indexes for APY data (modern era)
APY_INDEXES = [
    SelectiveMetagraphIndex.Tempo,
    SelectiveMetagraphIndex.MovingPrice,
    SelectiveMetagraphIndex.Hotkeys,
    SelectiveMetagraphIndex.Dividends,
    SelectiveMetagraphIndex.AlphaStake,
    SelectiveMetagraphIndex.AlphaDividendsPerHotkey,
]

SECONDS_PER_BLOCK = 12

# CSV column headers
CSV_HEADERS = [
    "block",
    "timestamp",
    "netuid",
    "hotkey",
    "alpha_earned",
    "alpha_staked",
    "tempo",
    "moving_price",
    "dividend_share",
    "is_legacy",
]


def compute_epoch_blocks(netuid: int, tempo: int, start: int, end: int) -> list[int]:
    """Compute blocks where epoch fires.

    Epoch fires when: (block + netuid + 1) % (tempo + 1) == 0
    """
    period = tempo + 1
    remainder = (start + netuid + 1) % period
    first = start if remainder == 0 else start + (period - remainder)
    return list(range(first, end + 1, period))


def _detect_api_boundary(
    subtensor: bt.Subtensor,
    netuid: int,
    start_block: int,
    end_block: int,
) -> int | None:
    """Binary search for the first block where getMetagraph/getSelectiveMetagraph works.

    Returns the boundary block, or None if the modern API is available for the
    entire range. Returns end_block + 1 if never available.
    """
    # Test end_block first
    try:
        result = subtensor.get_metagraph_info(netuid=netuid, block=end_block)
        if result is None:
            # Subnet doesn't exist — can't determine boundary
            return end_block + 1
    except (ValueError, Exception):
        # Modern API not available even at end — entire range is legacy
        return end_block + 1

    # Test start_block
    try:
        result = subtensor.get_metagraph_info(netuid=netuid, block=start_block)
        if result is not None:
            # Modern API available at start — entire range is modern
            return None
    except (ValueError, Exception):
        logger.debug("Modern API not available at start_block", block=start_block, netuid=netuid)

    # Binary search between start_block and end_block
    lo, hi = start_block, end_block
    while lo < hi:
        mid = (lo + hi) // 2
        try:
            result = subtensor.get_metagraph_info(netuid=netuid, block=mid)
            if result is not None:
                hi = mid  # works at mid, search lower
            else:
                lo = mid + 1
        except (ValueError, Exception):
            lo = mid + 1  # doesn't work at mid, search higher

    return lo


def _process_modern_epoch(writer, info, block_num: int, netuid: int) -> int:
    """Parse a MetagraphInfo response and write CSV records. Returns record count."""
    hotkeys = info.hotkeys or []

    # Build hotkey -> alpha_earned map from AlphaDividendsPerHotkey
    dividends_map: dict[str, float] = {}
    if info.alpha_dividends_per_hotkey:
        for hotkey, amount in info.alpha_dividends_per_hotkey:
            dividends_map[hotkey] = float(amount)

    if not dividends_map:
        return 0

    moving_price = float(info.moving_price) if info.moving_price else 0.0
    epoch_tempo = info.tempo if info.tempo else 360
    timestamp = block_num * SECONDS_PER_BLOCK
    records = 0

    for hotkey, alpha_earned_tao in dividends_map.items():
        try:
            uid = hotkeys.index(hotkey)
        except ValueError:
            continue

        alpha_staked_tao = float(info.alpha_stake[uid]) if info.alpha_stake else 0.0
        dividend_share = info.dividends[uid] if info.dividends else 0.0

        # Convert to rao
        alpha_earned_rao = int(alpha_earned_tao * 1e9)
        alpha_staked_rao = int(alpha_staked_tao * 1e9)

        if alpha_earned_rao == 0 and alpha_staked_rao == 0:
            continue

        writer.writerow(
            [
                block_num,
                timestamp,
                netuid,
                hotkey,
                alpha_earned_rao,
                alpha_staked_rao,
                epoch_tempo,
                moving_price,
                dividend_share,
                False,
            ]
        )
        records += 1

    return records


def _process_legacy_epoch(writer, neurons, block_num: int, netuid: int) -> int:
    """Parse NeuronInfoLite list and write CSV records with approximate alpha_earned.

    Legacy formula from requirements:
      validator_pool = total_emission * total_div_score / (total_div_score + total_inc_score)
      alpha_earned[uid] = validator_pool * (dividends[uid] / total_div_score)
      alpha_staked = sum of stake entries
    """
    if not neurons:
        return 0

    total_div_score = sum(n.dividends for n in neurons)
    total_inc_score = sum(n.incentive for n in neurons)
    total_emission = sum(float(n.emission) for n in neurons)

    if total_div_score + total_inc_score > 0:
        validator_pool = total_emission * total_div_score / (total_div_score + total_inc_score)
    else:
        validator_pool = total_emission

    timestamp = block_num * SECONDS_PER_BLOCK
    records = 0

    for neuron in neurons:
        if total_div_score > 0 and neuron.dividends > 0:
            alpha_earned_tao = validator_pool * (neuron.dividends / total_div_score)
        else:
            alpha_earned_tao = 0.0

        alpha_staked_tao = float(neuron.stake) if neuron.stake else 0.0

        alpha_earned_rao = int(alpha_earned_tao * 1e9)
        alpha_staked_rao = int(alpha_staked_tao * 1e9)

        if alpha_earned_rao == 0 and alpha_staked_rao == 0:
            continue

        writer.writerow(
            [
                block_num,
                timestamp,
                netuid,
                neuron.hotkey,
                alpha_earned_rao,
                alpha_staked_rao,
                360,
                0.0,
                neuron.dividends,
                True,
            ]
        )
        records += 1

    return records


class Command(BaseCommand):
    help = "Collect historical APY epoch data from a subtensor archive node."

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-block",
            type=int,
            required=True,
            help="Start of the block range to collect",
        )
        parser.add_argument(
            "--end-block",
            type=int,
            default=None,
            help="End of the block range (default: chain head)",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="./apy_data/",
            help="Directory to write CSV/JSON output",
        )
        parser.add_argument(
            "--subnets",
            type=int,
            nargs="*",
            default=None,
            help="Subnet IDs to collect (default: configured netuids)",
        )
        parser.add_argument(
            "--network",
            type=str,
            default=None,
            help="Bittensor network URI (default: BITTENSOR_ARCHIVE_NETWORK env var)",
        )
        parser.add_argument(
            "--limit-epochs",
            type=int,
            default=None,
            help="Limit epochs per subnet (for timing experiments)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show collection plan without querying",
        )

    def handle(self, *args, **options):
        start_block = options["start_block"]
        end_block = options["end_block"]
        output_dir = Path(options["output_dir"])
        subnets = options["subnets"]
        network = options["network"] or os.getenv("BITTENSOR_ARCHIVE_NETWORK", "archive")
        limit_epochs = options["limit_epochs"]
        dry_run = options["dry_run"]

        self.stdout.write(f"Connecting to {network}...")
        subtensor = bt.Subtensor(network=network)
        self.stdout.write(self.style.SUCCESS(f"Connected to {subtensor.network}"))

        if end_block is None:
            end_block = subtensor.block
            self.stdout.write(f"Chain head: {end_block}")

        if start_block > end_block:
            self.stderr.write(self.style.ERROR(f"--start-block ({start_block}) > --end-block ({end_block})"))
            return

        if subnets is None:
            subnets = MetagraphService.netuids_to_sync()
            if not subnets:
                self.stderr.write(self.style.ERROR("No subnets configured. Use --subnets"))
                return

        # Step 0: Detect API boundary
        self.stdout.write("\nDetecting API boundary (binary search on subnet 1)...")
        probe_netuid = subnets[0] if subnets else 1
        t0 = time.time()
        api_boundary = _detect_api_boundary(subtensor, probe_netuid, start_block, end_block)
        boundary_time = time.time() - t0

        if api_boundary is None:
            self.stdout.write(self.style.SUCCESS(f"  Modern API available for entire range ({boundary_time:.1f}s)"))
            api_boundary_block = start_block  # everything is modern
        elif api_boundary > end_block:
            self.stdout.write(
                self.style.WARNING(f"  Modern API NOT available — entire range is legacy ({boundary_time:.1f}s)")
            )
            api_boundary_block = end_block + 1  # everything is legacy
        else:
            self.stdout.write(f"  API boundary at block {api_boundary:,} ({boundary_time:.1f}s)")
            self.stdout.write(f"  Legacy era: {start_block:,} .. {api_boundary - 1:,}")
            self.stdout.write(f"  Modern era: {api_boundary:,} .. {end_block:,}")
            api_boundary_block = api_boundary

        # Compute epoch blocks per subnet (tempo=360 always)
        tempo = 360
        subnet_epochs: dict[int, list[int]] = {}
        total_epochs = 0
        total_legacy = 0
        total_modern = 0

        for netuid in subnets:
            epochs = compute_epoch_blocks(netuid, tempo, start_block, end_block)
            if limit_epochs:
                epochs = epochs[:limit_epochs]
            subnet_epochs[netuid] = epochs
            total_epochs += len(epochs)
            total_legacy += sum(1 for b in epochs if b < api_boundary_block)
            total_modern += sum(1 for b in epochs if b >= api_boundary_block)

        # Print plan
        self.stdout.write(f"\nBlock range: {start_block:,} -> {end_block:,} ({end_block - start_block:,} blocks)")
        self.stdout.write(f"Subnets: {subnets}")
        self.stdout.write(f"Tempo: {tempo} (period={tempo + 1})")
        self.stdout.write(f"Total epochs: {total_epochs:,} (legacy={total_legacy:,}, modern={total_modern:,})")
        if limit_epochs:
            self.stdout.write(f"  (limited to {limit_epochs} per subnet)")
        for netuid in subnets:
            ep = subnet_epochs[netuid]
            if ep:
                n_leg = sum(1 for b in ep if b < api_boundary_block)
                n_mod = len(ep) - n_leg
                self.stdout.write(
                    f"  Subnet {netuid}: {len(ep):,} epochs ({ep[0]}..{ep[-1]}) [legacy={n_leg}, modern={n_mod}]"
                )
            else:
                self.stdout.write(f"  Subnet {netuid}: 0 epochs")

        if dry_run:
            full_epochs = sum(len(compute_epoch_blocks(n, tempo, start_block, end_block)) for n in subnets)
            self.stdout.write(f"\nFull collection would query {full_epochs:,} epochs")
            self.stdout.write(self.style.WARNING("Dry run - no queries made"))
            return

        self._collect(
            subtensor,
            subnet_epochs,
            subnets,
            tempo,
            start_block,
            end_block,
            api_boundary_block,
            output_dir,
            network,
            limit_epochs,
        )

    def _collect(
        self,
        subtensor: bt.Subtensor,
        subnet_epochs: dict[int, list[int]],
        subnets: list[int],
        tempo: int,
        start_block: int,
        end_block: int,
        api_boundary_block: int,
        output_dir: Path,
        network: str,
        limit_epochs: int | None,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = output_dir / "epoch_records.csv"
        metadata_path = output_dir / "run_metadata.json"
        failed_path = output_dir / "failed_epochs.json"

        started_at = datetime.now(UTC)
        total_records = 0
        total_queried = 0
        legacy_count = 0
        modern_count = 0
        failed_epochs: list[dict] = []
        query_times: list[float] = []

        try:
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_HEADERS)

                for netuid in subnets:
                    epochs = subnet_epochs[netuid]
                    n_epochs = len(epochs)
                    self.stdout.write(f"\nSubnet {netuid}: collecting {n_epochs} epochs...")

                    for i, block_num in enumerate(epochs):
                        try:
                            is_legacy = block_num < api_boundary_block
                            t0 = time.time()

                            if is_legacy:
                                epoch_records = self._query_legacy(
                                    subtensor,
                                    writer,
                                    netuid,
                                    block_num,
                                )
                                legacy_count += 1
                            else:
                                epoch_records = self._query_modern(
                                    subtensor,
                                    writer,
                                    netuid,
                                    block_num,
                                )
                                modern_count += 1

                            elapsed = time.time() - t0
                            query_times.append(elapsed)
                            total_queried += 1
                            total_records += epoch_records

                            if (i + 1) % 10 == 0 or i == 0:
                                avg_time = sum(query_times[-10:]) / len(query_times[-10:])
                                remaining = (n_epochs - i - 1) * avg_time
                                era = "L" if is_legacy else "M"
                                self.stdout.write(
                                    f"  {i + 1}/{n_epochs} ({(i + 1) / n_epochs * 100:.0f}%) "
                                    f"block={block_num} [{era}] recs={epoch_records} "
                                    f"t={elapsed:.2f}s avg={avg_time:.2f}s "
                                    f"ETA={remaining:.0f}s"
                                )

                        except KeyboardInterrupt:
                            raise
                        except Exception as e:
                            failed_epochs.append(
                                {
                                    "netuid": netuid,
                                    "block": block_num,
                                    "error": str(e),
                                }
                            )
                            logger.exception("Failed epoch query", netuid=netuid, block=block_num)
                            self.stderr.write(self.style.ERROR(f"  block {block_num}: {e}"))

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nInterrupted by user"))

        finished_at = datetime.now(UTC)

        # Write metadata
        avg_query = sum(query_times) / len(query_times) if query_times else 0
        metadata = {
            "start_block": start_block,
            "end_block": end_block,
            "api_boundary_block": api_boundary_block,
            "collection_started_at": started_at.isoformat(),
            "collection_finished_at": finished_at.isoformat(),
            "total_epochs_collected": total_queried,
            "total_records": total_records,
            "legacy_epochs": legacy_count,
            "modern_epochs": modern_count,
            "subnets_collected": subnets,
            "network": network,
            "avg_query_time_s": round(avg_query, 4),
            "total_query_time_s": round(sum(query_times), 2),
        }
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        if failed_epochs:
            with open(failed_path, "w") as f:
                json.dump(failed_epochs, f, indent=2)

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Collection complete"))
        self.stdout.write(f"  Epochs queried:  {total_queried:,} (legacy={legacy_count:,}, modern={modern_count:,})")
        self.stdout.write(f"  Records written: {total_records:,}")
        self.stdout.write(f"  Failed epochs:   {len(failed_epochs)}")

        if query_times:
            self.stdout.write(f"  Avg query time:  {avg_query:.3f}s")
            self.stdout.write(f"  Total time:      {sum(query_times):.1f}s")

            if limit_epochs:
                full_epochs = sum(len(compute_epoch_blocks(n, tempo, start_block, end_block)) for n in subnets)
                est_s = full_epochs * avg_query
                est_h = est_s / 3600
                self.stdout.write("\n  --- Full collection estimate ---")
                self.stdout.write(f"  Total epochs:  {full_epochs:,}")
                self.stdout.write(f"  Est. time:     {est_h:.1f}h ({est_s:,.0f}s)")

        self.stdout.write(f"\n  Output:   {csv_path}")
        self.stdout.write(f"  Metadata: {metadata_path}")
        if failed_epochs:
            self.stdout.write(f"  Failures: {failed_path}")

    def _query_modern(
        self,
        subtensor: bt.Subtensor,
        writer,
        netuid: int,
        block_num: int,
    ) -> int:
        """Query using selective metagraph (modern era). Falls back to full metagraph,
        then to neurons_lite if selective call fails."""
        # Try selective metagraph first
        try:
            info = subtensor.get_metagraph_info(
                netuid=netuid,
                selected_indices=APY_INDEXES,
                block=block_num,
            )
            if info is not None:
                return _process_modern_epoch(writer, info, block_num, netuid)
        except ValueError:
            pass  # selective not available at this block, try full

        # Fallback: full metagraph (no selected_indices)
        try:
            info = subtensor.get_metagraph_info(netuid=netuid, block=block_num)
            if info is not None:
                return _process_modern_epoch(writer, info, block_num, netuid)
        except (ValueError, Exception):
            logger.debug("Full metagraph unavailable, falling back to legacy", block=block_num, netuid=netuid)

        # Final fallback: legacy neurons_lite
        return self._query_legacy(subtensor, writer, netuid, block_num)

    @staticmethod
    def _query_legacy(
        subtensor: bt.Subtensor,
        writer,
        netuid: int,
        block_num: int,
    ) -> int:
        """Query using getNeuronsLite (legacy era)."""
        neurons = subtensor.neurons_lite(netuid=netuid, block=block_num)
        if not neurons:
            return 0
        return _process_legacy_epoch(writer, neurons, block_num, netuid)
