from abstract_block_dumper.v1.decorators import block_task


@block_task(condition=lambda block_number: block_number % 2 == 0)
def process_every_even_block(block_number: int) -> int:
    print(f"Processing every even block: {block_number}")
    return block_number
