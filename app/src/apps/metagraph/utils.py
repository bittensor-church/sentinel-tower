from math import floor

from django.conf import settings


def get_dumpable_blocks(epoch: range) -> tuple[int, ...]:
    """
    Get the blocks that should be dumped for the given epoch.

    Note: always includes the end of epoch block.

    Example NUM_BLOCK_DUMPS_PER_EPOCH=3 and tempo=360:
        [epoch_start, epoch_start + 120, epoch_start + 240, epoch_end (epoch_start + 360)]
    """
    step = settings.TEMPO / settings.NUM_BLOCK_DUMPS_PER_EPOCH
    ranges = [floor(epoch.start + step * i) for i in range(settings.NUM_BLOCK_DUMPS_PER_EPOCH)]

    # Always inject the end of the epoch
    end_epoch = epoch.start + settings.TEMPO
    ranges.append(end_epoch)
    return tuple(ranges)


def get_epoch_containing_block(block: int, netuid: int = 0) -> range:
    """For given subnet returns range of blocks for epoch containing given block."""
    next_epoch_block = get_next_epoch_block(block, netuid, settings.TEMPO)
    return range(next_epoch_block - get_epoch_duration(settings.TEMPO), next_epoch_block)


def get_next_epoch_block(block: int, netuid: int = 0, tempo: int = 360) -> int:
    """Get the block number of the next epoch for given subnet."""
    return block + (get_blocks_until_next_epoch(block, netuid, tempo) or get_epoch_duration(tempo))


def get_epoch_duration(tempo: int) -> int:
    """
    Get the duration of an epoch based on the tempo.

    Note: Because of a bittensor bug, the epoch duration is tempo + 1.
    """
    return tempo + 1


def get_blocks_until_next_epoch(block_number: int, netuid: int, tempo: int = 360) -> int:
    """Get number of blocks until the next epoch for given subnet."""
    index: int = block_index_in_epoch(block_number, netuid, tempo)
    return 0 if index == 0 else get_epoch_duration(tempo) - index


def block_index_in_epoch(block: int, netuid: int, tempo: int) -> int:
    """
    Get the index of the block in the current epoch.
    """
    return (block + netuid + 2) % get_epoch_duration(tempo)
