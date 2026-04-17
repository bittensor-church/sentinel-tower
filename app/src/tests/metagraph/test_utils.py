from apps.metagraph.utils import (
    TEMPO,
    block_index_in_epoch,
    epoch_start_blocks_in_range,
)


class TestEpochStartBlocksInRange:
    def test_returns_only_epoch_start_blocks(self):
        netuid = 1
        result = epoch_start_blocks_in_range(1000, 5000, netuid)
        assert result, "expected at least one epoch-start in this range"
        assert all(block_index_in_epoch(b, netuid, TEMPO) == 0 for b in result)

    def test_blocks_are_sorted_ascending(self):
        result = epoch_start_blocks_in_range(1000, 5000, netuid=1)
        assert result == sorted(result)

    def test_consecutive_blocks_differ_by_epoch_duration(self):
        result = epoch_start_blocks_in_range(1000, 10000, netuid=1)
        assert len(result) >= 2
        diffs = {b2 - b1 for b1, b2 in zip(result, result[1:])}
        assert diffs == {361}

    def test_inclusive_endpoints(self):
        # For netuid=0: (B + 2) % 361 == 0 => B % 361 == 359 => first start is 359
        netuid = 0
        result = epoch_start_blocks_in_range(359, 359, netuid)
        assert result == [359]

    def test_empty_range_returns_empty(self):
        netuid = 0
        # Range [0, 50] contains no B with (B+2) % 361 == 0
        result = epoch_start_blocks_in_range(0, 50, netuid)
        assert result == []

    def test_per_netuid_offset_differs(self):
        r1 = epoch_start_blocks_in_range(1000, 2000, netuid=1)
        r2 = epoch_start_blocks_in_range(1000, 2000, netuid=2)
        assert set(r1).isdisjoint(set(r2))

    def test_handles_start_greater_than_end(self):
        result = epoch_start_blocks_in_range(5000, 1000, netuid=1)
        assert result == []
